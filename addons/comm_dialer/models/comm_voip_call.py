# -*- coding: utf-8 -*-
import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
RECORDING_MANAGER_GROUP = 'comm_whatsapp_calling.group_whatsapp_call_recording_manager'


class CommVoipCall(models.Model):
    # Transcription + AI insights come from the shared mixin (also on whatsapp.call.log).
    _name = 'comm.voip.call'
    _inherit = ['comm.voip.call', 'comm.call.transcription.mixin']

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
    # The agent's browser softphone mixes both audio tracks and uploads the
    # result (see /voip/call/upload_recording + softphone_service.js). res_field
    # keeps these apart from any other attachment on the call.
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

    def write(self, vals):
        res = super().write(vals)
        # Whenever a call is closed out (end_time set), fill duration from the
        # span if it wasn't provided, and surface the call in the omnichannel
        # inbox as a conversation interaction — covers softphone + ARI paths.
        if vals.get('end_time'):
            for c in self:
                if c.end_time and c.start_time and not c.duration:
                    secs = int((c.end_time - c.start_time).total_seconds())
                    if secs > 0:
                        super(CommVoipCall, c).write({'duration': secs})
                c._sync_to_conversation()
        return res

    def _transcript_speaker_labels(self):
        # Label the remote side with the partner's name when known.
        caller = (self.partner_id.name if self.partner_id else '') or 'Caller'
        return 'Agent', caller

    def _do_transcription(self):
        # After (re)transcribing, refresh the inbox interaction so the transcript
        # + AI summary show in the conversation timeline.
        super()._do_transcription()
        self._sync_to_conversation()

    @api.model
    def _cron_transcribe_all(self):
        """Cron entry point — transcribe every recorded call, all types, plus
        inbound WhatsApp voice notes (same Whisper + Claude pipeline)."""
        self._cron_transcribe_pending()
        self.env['whatsapp.call.log']._cron_transcribe_pending()
        self.env['whatsapp.message']._cron_transcribe_voice_notes()

    def _find_or_create_partner(self):
        """Match the call's number to a res.partner (tolerant last-9-digits
        match), or create one. Creation is gated by comm_dialer.auto_create_partner
        (default on) so it can be turned off for POPIA-strict setups."""
        self.ensure_one()
        number = (self.to_number if self.direction == 'outgoing' else self.from_number) or ''
        number = number.strip()
        if not number:
            return self.env['res.partner']
        Partner = self.env['res.partner']
        digits = re.sub(r'\D', '', number)
        partner = Partner.browse()
        if len(digits) >= 6:
            tail = digits[-9:]  # national significant number, format-tolerant
            partner = Partner.search(
                ['|', ('phone', 'like', tail), ('mobile', 'like', tail)], limit=1)
        if not partner:
            partner = Partner.search(
                ['|', ('phone', '=', number), ('mobile', '=', number)], limit=1)
        if not partner:
            allow = self.env['ir.config_parameter'].sudo().get_param(
                'comm_dialer.auto_create_partner', '1')
            if allow not in ('0', 'False', 'false'):
                partner = Partner.create({'name': number, 'phone': number})
        return partner

    def _sync_to_conversation(self):
        """Surface this VoIP call in the omnichannel inbox: find/open a
        comm.conversation for the partner on the 'voip' channel and add (or
        update) a call interaction. Idempotent; skipped without a partner."""
        self.ensure_one()
        if not self.partner_id:
            partner = self._find_or_create_partner()
            if partner:
                self.partner_id = partner.id
        if not self.partner_id:
            return
        channel = self.env.ref('comm_chatbot_voip.channel_voip', raise_if_not_found=False)
        if not channel:
            return
        Conv = self.env['comm.conversation']
        conv = self.conversation_id
        if not conv:
            conv = Conv.search([
                ('partner_id', '=', self.partner_id.id),
                ('lifecycle_state', 'in', ('open', 'waiting')),
            ], limit=1, order='last_activity_at desc')
            if not conv:
                conv = Conv.create({
                    'partner_id': self.partner_id.id,
                    'primary_channel_id': channel.id,
                })
            self.conversation_id = conv.id

        direction = 'inbound' if self.direction == 'incoming' else 'outbound'
        state_label = dict(self._fields['state'].selection).get(self.state, self.state or '')
        body = '\U0001F4DE %s call — %s (%s)' % (
            'Inbound' if direction == 'inbound' else 'Outbound',
            self.duration_display or '—', state_label)
        if self.ai_summary:
            body += '\n' + self.ai_summary
        if self.transcript:
            body += '\n\nTranscript:\n' + self.transcript

        Interaction = self.env['comm.interaction']
        existing = Interaction.search([
            ('source_model', '=', 'comm.voip.call'), ('source_id', '=', self.id)], limit=1)
        if existing:
            existing.write({'raw_body': body, 'rendered_body': body})
        else:
            Interaction.create({
                'conversation_id': conv.id,
                'channel_id': channel.id,
                'direction': direction,
                'at': self.end_time or self.start_time or fields.Datetime.now(),
                'raw_body': body,
                'rendered_body': body,
                'status': 'received',
                'source_model': 'comm.voip.call',
                'source_id': self.id,
            })
        conv.touch()

        # Also surface in the Gen-1 Contact Centre inbox, if that stack is installed.
        if 'contact.centre.contact' in self.env:
            try:
                self.env['contact.centre.contact'].sudo()._sync_voip_call(self)
            except Exception:
                _logger.exception("comm_dialer: Gen-1 inbox sync failed for call %s", self.id)

    @api.depends('recording_ids')
    def _compute_has_recording(self):
        for rec in self:
            rec.has_recording = bool(rec.recording_ids)

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
