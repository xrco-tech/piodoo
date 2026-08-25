# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    # Give inbound WhatsApp voice notes the same Whisper transcription + Claude
    # insights as VoIP / WhatsApp calls, reusing the shared mixin. A voice note's
    # audio is already downloaded by comm_whatsapp into media_attachment_id, so we
    # just expose it as recording_ids for the mixin and queue it for the cron.
    _name = 'whatsapp.message'
    _inherit = ['whatsapp.message', 'comm.call.transcription.mixin']

    # The mixin transcribes self.recording_ids[:1]; for a voice note that's the
    # single downloaded audio attachment. Computed (not stored) — searches in the
    # cron go through the concrete audio/media_attachment_id fields instead.
    recording_ids = fields.Many2many(
        'ir.attachment', compute='_compute_recording_ids', string='Voice Note Audio')

    @api.depends('media_attachment_id', 'message_type')
    def _compute_recording_ids(self):
        for rec in self:
            rec.recording_ids = (
                rec.media_attachment_id
                if rec.message_type == 'audio' and rec.media_attachment_id
                else self.env['ir.attachment'])

    def _is_transcribable_voice_note(self):
        self.ensure_one()
        return bool(self.message_type == 'audio'
                    and self.is_incoming
                    and self.media_attachment_id)

    @api.model
    def create_from_webhook(self, webhook_data, entry_data):
        record = super().create_from_webhook(webhook_data, entry_data)
        # Queue inbound voice notes for transcription. We DON'T transcribe inline:
        # the webhook must return fast, and Whisper can take many seconds — the
        # cron (_cron_transcribe_voice_notes) picks up 'pending' records. Gated by
        # comm_dialer.auto_transcribe_voice_notes (default on), mirroring the
        # auto-record-all toggle for calls.
        if record and record._is_transcribable_voice_note():
            auto = self.env['ir.config_parameter'].sudo().get_param(
                'comm_dialer.auto_transcribe_voice_notes', '1')
            if auto not in ('0', 'False', 'false'):
                record.transcript_state = 'pending'
        return record

    @api.model
    def _cron_transcribe_voice_notes(self, limit=3):
        """Transcribe queued (and any not-yet-done) inbound voice notes.

        Small batch on purpose — see _cron_transcribe_pending: keeps Whisper
        responsive and the ir_cron lock window short.
        """
        pending = self.search([
            ('message_type', '=', 'audio'),
            ('is_incoming', '=', True),
            ('media_attachment_id', '!=', False),
            ('transcript_state', 'in', ('none', 'pending')),
        ], limit=limit)
        for rec in pending:
            rec._do_transcription()
