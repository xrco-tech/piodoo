# -*- coding: utf-8 -*-

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = "whatsapp.message"

    @api.model
    def create_from_webhook(self, webhook_data, entry_data):
        record = super().create_from_webhook(webhook_data, entry_data)
        if record:
            try:
                self.env["contact.centre.contact"].sudo()._sync_whatsapp_message(record)
            except Exception:
                _logger.exception(
                    "contact_centre_sync: failed to mirror whatsapp.message %s into contact_centre",
                    record.id,
                )
        return record
