# -*- coding: utf-8 -*-

from odoo import _, models
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

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
