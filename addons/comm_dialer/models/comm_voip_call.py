# -*- coding: utf-8 -*-
import base64
import json
import logging
import re

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
RECORDING_MANAGER_GROUP = 'comm_whatsapp_calling.group_whatsapp_call_recording_manager'


class CommVoipCall(models.Model):
    _inherit = 'comm.voip.call'

    # Back-link so a call originated by the dialer knows its call-list row.
    dialer_contact_id = fields.Many2one(
        'comm.dialer.contact', 'Dialer Contact',
        ondelete='set null', index=True)
    # Progressive pre-assigns a specific agent at dial time; predictive leaves
    # this empty and the bridge service binds a Ready agent on answer.
    dialer_agent_session_id = fields.Many2one(
        'comm.dialer.agent.session', 'Assigned Agent', ondelete='set null')
    # Convenience reads for the ARI bridge service (via search_read).
    agent_sip_ext = fields.Char(related='dialer_agent_session_id.sip_ext')
    dialer_campaign_id = fields.Many2one(
        related='dialer_contact_id.campaign_id', store=True,
        string='Dialer Campaign', index=True)

    # ── Recording ─────────────────────────────────────────────────────────
    # Mirrors comm_whatsapp_calling: the agent's browser softphone mixes both
    # audio tracks and uploads the result (see /voip/call/upload_recording and
    # static/src/softphone/softphone_service.js). res_field keeps these apart
    # from any other attachment on the call.
    recording_ids = fields.One2many(
        'ir.attachment', 'res_id', string='Recordings',
        domain=lambda self: [
            ('res_model', '=', 'comm.voip.call'),
            ('res_field', '=', 'recording_ids'),
        ],
    )
    has_recording = fields.Boolean(
        string='Recorded', compute='_compute_has_recording', store=False)
    recording_player_html = fields.Html(
        string='Recording', compute='_compute_recording_player_html', sanitize=False)

    # ── Transcription & AI insights ────────────────────────────────────────
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

    def write(self, vals):
        res = super().write(vals)
        # Whenever a call is closed out (end_time set), fill duration from the
        # span if it wasn't provided — covers softphone + ARI bridge paths.
        if vals.get('end_time'):
            for c in self:
                if c.end_time and c.start_time and not c.duration:
                    secs = int((c.end_time - c.start_time).total_seconds())
                    if secs > 0:
                        super(CommVoipCall, c).write({'duration': secs})
        return res

    @api.depends('recording_ids')
    def _compute_has_recording(self):
        for rec in self:
            rec.has_recording = bool(rec.recording_ids)

    # ── Transcription (self-hosted Whisper) + Claude insights ───────────────
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
        # Reuse whichever Anthropic key the instance already has configured
        # (Gen-2 chatbot key, or the Gen-1 copilot key).
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
            _logger.exception("comm_dialer: transcription failed for call %s", self.id)
            self.write({'transcript_state': 'failed'})
            return
        vals = {'transcript': text or '', 'transcript_state': 'done'}
        # AI insights are best-effort — never lose the transcript if they fail.
        if text:
            try:
                insights = self._run_ai_insights(text)
            except Exception:
                _logger.exception("comm_dialer: AI insights failed for call %s", self.id)
                insights = {}
            if insights:
                vals['ai_summary'] = (insights.get('summary') or '')[:2000]
                sentiment = (insights.get('sentiment') or '').strip().lower()
                if sentiment in ('positive', 'neutral', 'negative'):
                    vals['ai_sentiment'] = sentiment
                vals['ai_suggested_disposition'] = (insights.get('disposition') or '')[:120]
        self.write(vals)

    def action_transcribe(self):
        for call in self:
            call._do_transcription()
        return True

    @api.model
    def _cron_transcribe_pending(self, limit=20):
        """Process queued recordings. Disabled cron by default — enable once the
        Whisper service (docker-compose.whisper.yml) is up."""
        pending = self.search([('transcript_state', '=', 'pending'),
                               ('recording_ids', '!=', False)], limit=limit)
        for call in pending:
            call._do_transcription()

    @api.depends('recording_ids')
    def _compute_recording_player_html(self):
        can_download = self.env.user.has_group(RECORDING_MANAGER_GROUP)
        for rec in self:
            if not rec.recording_ids:
                rec.recording_player_html = False
                continue
            parts = []
            for att in rec.recording_ids:
                src = '/voip/call/recording/%s' % att.id
                download_link = (
                    '<a href="%s?download=1" style="margin-left:10px;">Download</a>' % src
                    if can_download else '')
                duration_label = (
                    '<span style="margin-left:10px;color:#6b7280;">%s</span>'
                    % att.recording_duration_display
                    if att.recording_duration_display else '')
                parts.append(
                    '<div style="margin-bottom:10px;display:flex;align-items:center;">'
                    '<audio controls preload="none" src="%s" style="max-width:420px;"></audio>'
                    '%s%s</div>' % (src, duration_label, download_link))
            rec.recording_player_html = ''.join(parts)
