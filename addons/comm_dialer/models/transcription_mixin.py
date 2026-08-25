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
            # Generous per-request timeout: measured ~1.5x realtime on the box's
            # 'small' model, so a multi-minute call recording legitimately needs
            # well over 180s. The cron's lock window is bounded by the small batch
            # limit below (not by this timeout), and deploys use the stop-odoo
            # rule — so favour completing long transcriptions over a tight cap.
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

    # ── Dual-channel (per-speaker) transcription ───────────────────────────
    # When the softphone captures the agent and remote party on separate mono
    # streams (uploaded as res_field rec_channel_agent / rec_channel_caller),
    # we transcribe each side independently and interleave by timestamp so the
    # transcript is speaker-labelled — deterministic, since the label comes from
    # which audio channel the words are on, not from guessing.
    def _channel_recordings(self):
        self.ensure_one()
        Att = self.env['ir.attachment'].sudo()
        base = [('res_model', '=', self._name), ('res_id', '=', self.id)]
        agent = Att.search(base + [('res_field', '=', 'rec_channel_agent')], order='id desc', limit=1)
        caller = Att.search(base + [('res_field', '=', 'rec_channel_caller')], order='id desc', limit=1)
        return agent, caller

    def _transcript_speaker_labels(self):
        """(agent_label, caller_label) — overridable per call type."""
        return 'Agent', 'Caller'

    def _asr_segments(self, att, label):
        """Transcribe one mono channel; return [(start_seconds, label, text)]."""
        audio = base64.b64decode(att.datas or b'')
        if not audio:
            return []
        resp = requests.post(
            self._whisper_url() + '/asr',
            # vad_filter skips the long silences on each mono channel (while the
            # other party speaks), which otherwise make Whisper hallucinate text.
            params={'task': 'transcribe', 'output': 'json', 'encode': 'true',
                    'vad_filter': 'true'},
            files={'audio_file': (att.name or 'audio.webm', audio, att.mimetype or 'audio/webm')},
            timeout=600,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            return []
        out = []
        for seg in (data.get('segments') or []):
            text = (seg.get('text') or '').strip()
            if text:
                out.append((float(seg.get('start') or 0.0), label, text))
        return out

    def _transcribe_dual_channel(self, agent_att, caller_att):
        a_label, c_label = self._transcript_speaker_labels()
        segs = self._asr_segments(agent_att, a_label) + self._asr_segments(caller_att, c_label)
        segs.sort(key=lambda s: s[0])
        # Merge consecutive same-speaker segments into one turn for readability.
        turns = []
        for _start, label, text in segs:
            if turns and turns[-1][0] == label:
                turns[-1][1] += ' ' + text
            else:
                turns.append([label, text])
        return '\n'.join('%s: %s' % (lbl, txt) for lbl, txt in turns)

    def _apply_transcript(self, text):
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

    def _do_transcription(self):
        self.ensure_one()
        agent_att, caller_att = self._channel_recordings()
        dual = bool(agent_att and caller_att)
        if not dual and not self.recording_ids:
            self.transcript_state = 'none'
            return
        try:
            text = (self._transcribe_dual_channel(agent_att, caller_att)
                    if dual else self._transcribe_recording())
        except Exception:
            _logger.exception("transcription failed for %s %s", self._name, self.id)
            self.write({'transcript_state': 'failed'})
            return
        self._apply_transcript(text)
        # The per-channel mono files are only needed to produce the transcript —
        # drop them once done so storage stays as lean as the single mixed file.
        if dual:
            try:
                (agent_att | caller_att).sudo().unlink()
            except Exception:
                _logger.exception("cleanup of channel recordings failed for %s %s", self._name, self.id)

    def action_transcribe(self):
        for rec in self:
            rec._do_transcription()
        return True

    @api.model
    def _cron_transcribe_pending(self, limit=3):
        """Transcribe any recorded call not yet done — voip + whatsapp + …

        Small batches on purpose: the 'small' model runs ~1.5x realtime, so a
        big batch of (long) call recordings both floods Whisper and holds the
        ir_cron row lock for the whole run. limit=3 keeps each run short, lets
        Whisper stay responsive, and still drains a backlog steadily (runs are
        serialized — the lock stops a new run starting before the last ends).
        """
        pending = self.search([('transcript_state', 'in', ('none', 'pending')),
                               ('recording_ids', '!=', False)], limit=limit)
        for rec in pending:
            rec._do_transcription()
