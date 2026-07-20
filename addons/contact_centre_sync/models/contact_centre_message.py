# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ContactCentreMessage(models.Model):
    _inherit = "contact.centre.message"

    channel = fields.Selection(selection_add=[("voice", "Voice")], ondelete={"voice": "cascade"})
    whatsapp_call_log_id = fields.Many2one("whatsapp.call.log", ondelete="set null", index=True)

    # Surfaced so the Inbox thread pane can offer inline playback right
    # on a call's message bubble, without a second round trip through
    # whatsapp.call.log — reuses the same streaming route/permissions
    # as everywhere else (comm_whatsapp_calling's /whatsapp/call/
    # recording/<id> route already gates read vs. download correctly).
    call_recording_id = fields.Many2one(
        "ir.attachment", compute="_compute_call_recording_id", store=False,
    )
    call_recording_duration = fields.Char(
        related="call_recording_id.recording_duration_display", string="Recording Length",
    )

    @api.depends("whatsapp_call_log_id.recording_ids")
    def _compute_call_recording_id(self):
        for rec in self:
            rec.call_recording_id = rec.whatsapp_call_log_id.recording_ids[:1]
