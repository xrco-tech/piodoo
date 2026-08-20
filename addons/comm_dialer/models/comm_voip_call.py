# -*- coding: utf-8 -*-
from odoo import api, fields, models

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
