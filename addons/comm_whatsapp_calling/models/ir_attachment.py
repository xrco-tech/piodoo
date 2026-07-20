# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    # Set at upload time by the browser that recorded the call (it's the
    # only party that actually knows how long the MediaRecorder session
    # ran) — see comm_whatsapp_calling's /whatsapp/call/upload_recording
    # route and static/src/js/incoming_call_popup.js.
    recording_duration = fields.Integer(string="Recording Duration (s)")
    recording_duration_display = fields.Char(
        string="Recording Duration", compute="_compute_recording_duration_display",
    )

    @api.depends("recording_duration")
    def _compute_recording_duration_display(self):
        for att in self:
            secs = att.recording_duration or 0
            att.recording_duration_display = f"{secs // 60}:{secs % 60:02d}" if secs else ""

    def _is_call_recording(self):
        return self.filtered(
            lambda a: a.res_model == "whatsapp.call.log" and a.res_field == "recording_ids"
        )

    def unlink(self):
        # Superuser/sudo calls are trusted system operations (e.g. the
        # retention cron purging expired recordings) — only gate actual
        # user-initiated deletes.
        if not self.env.su:
            recordings = self._is_call_recording()
            if recordings and not self.env.user.has_group(
                    "comm_whatsapp_calling.group_whatsapp_call_recording_manager"):
                raise AccessError(_(
                    "Only a Call Recording Manager can delete call recordings."
                ))
        return super().unlink()
