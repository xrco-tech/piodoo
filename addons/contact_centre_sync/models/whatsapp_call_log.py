# -*- coding: utf-8 -*-

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_CALL_TERMINAL_FIELDS = {"call_status", "duration", "is_missed"}


class WhatsappCallLog(models.Model):
    _inherit = "whatsapp.call.log"

    def _sync_to_contact_centre(self):
        try:
            self.env["contact.centre.contact"].sudo()._sync_whatsapp_call(self)
        except Exception:
            _logger.exception(
                "contact_centre_sync: failed to mirror whatsapp.call.log %s into contact_centre",
                self.id,
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._sync_to_contact_centre()
        return records

    def write(self, vals):
        result = super().write(vals)
        if _CALL_TERMINAL_FIELDS & set(vals.keys()):
            for record in self:
                record._sync_to_contact_centre()
        return result
