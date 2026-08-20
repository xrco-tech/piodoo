# -*- coding: utf-8 -*-
"""Reusable call-recording transcription + AI insights.

Any model with a ``recording_ids`` One2many of audio ir.attachments (VoIP calls,
WhatsApp calls, …) can inherit this mixin to get self-hosted Whisper transcription
plus Claude summary/sentiment/disposition — one implementation for every call type.
"""
import base64
import json
import logging
import re

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CallTranscriptionMixin(models.AbstractModel):
    _name = 'comm.call.transcription.mixin'
    _description = 'Call Recording Transcription + AI Insights'

    transcript = fields.Text('Transcript')
    transcript_state = fields.Selection([
        ('none', 'Not transcribed'),
        ('pending', 'Queued'),
        ('done', 'Transcribed'),
        ('failed', 'Failed'),
    ], default='none', index=True)
    ai_summary = fields.Text('AI Summary')
    ai_sentiment = fields.Selection([
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('negative', 'Negative'),
    ], string='Sentiment')
    ai_suggested_disposition = fields.Char('Suggested Disposition')

    # ── Transcription (self-hosted Whisper) ────────────────────────────────
    def _whisper_url(self):
        return (self.env['ir.config_parameter'].sudo().get_param('comm_dialer.whisper_url')
                or 'http://whisper:9000').rstrip('/')

    def _transcribe_recording(self):
        """POST the latest recording audio to the self-hosted Whisper service
        (audio never leaves the box). Returns the transcript text."""
        self.ensure_one()
        att = self.recording_ids[:1]
        if not att:
            return ''
        audio = base64.b64decode(att.datas or b'')
        if not audio:
            return ''
        resp = requests.post(
            self._whisper_url() + '/asr',
            params={'task': 'transcribe', 'output': 'txt', 'encode': 'true'},
            files={'audio_file': (att.name or 'audio.webm', audio, att.mimetype or 'audio/webm')},
            timeout=600,
        )
        resp.raise_for_status()
        return (resp.text or '').strip()

    def _run_ai_insights(self, transcript):
        """Claude: 1-2 sentence summary + sentiment + suggested disposition."""
        if not transcript:
            return {}
        ICP = self.env['ir.config_parameter'].sudo()
        key = (ICP.get_param('comm_chatbot.anthropic_api_key')
               or ICP.get_param('whatsapp.anthropic_api_key') or '').strip()
        if not key:
            return {}
        model = ICP.get_param('comm_dialer.insight_model') or 'claude-haiku-4-5-20251001'
        prompt = (
            "You are a contact-centre QA assistant. Read the call transcript and reply with "
            'STRICT JSON only, no prose: {"summary": "<1-2 sentence summary>", '
            '"sentiment": "positive|neutral|negative", '
            '"disposition": "<short suggested call-outcome label>"}.\n\n'
            "Transcript:\n" + transcript[:8000]
        )
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                     'content-type': 'application/json'},
            json={'model': model, 'max_tokens': 400,
                  'messages': [{'role': 'user', 'content': prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        text = ''.join(b.get('text', '') for b in resp.json().get('content', [])
                       if b.get('type') == 'text')
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except ValueError:
            return {}

    def _do_transcription(self):
        self.ensure_one()
        if not self.recording_ids:
            self.transcript_state = 'none'
            return
        try:
            text = self._transcribe_recording()
        except Exception:
            _logger.exception("transcription failed for %s %s", self._name, self.id)
            self.write({'transcript_state': 'failed'})
            return
        vals = {'transcript': text or '', 'transcript_state': 'done'}
        # AI insights are best-effort — never lose the transcript if they fail.
        if text:
            try:
                insights = self._run_ai_insights(text)
            except Exception:
                _logger.exception("AI insights failed for %s %s", self._name, self.id)
                insights = {}
            if insights:
                vals['ai_summary'] = (insights.get('summary') or '')[:2000]
                sentiment = (insights.get('sentiment') or '').strip().lower()
                if sentiment in ('positive', 'neutral', 'negative'):
                    vals['ai_sentiment'] = sentiment
                vals['ai_suggested_disposition'] = (insights.get('disposition') or '')[:120]
        self.write(vals)

    def action_transcribe(self):
        for rec in self:
            rec._do_transcription()
        return True

    @api.model
    def _cron_transcribe_pending(self, limit=20):
        """Transcribe any recorded call not yet done — voip + whatsapp + …"""
        pending = self.search([('transcript_state', 'in', ('none', 'pending')),
                               ('recording_ids', '!=', False)], limit=limit)
        for rec in pending:
            rec._do_transcription()
