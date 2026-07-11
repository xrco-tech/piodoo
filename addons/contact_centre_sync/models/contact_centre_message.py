# -*- coding: utf-8 -*-

from odoo import fields, models


class ContactCentreMessage(models.Model):
    _inherit = "contact.centre.message"

    channel = fields.Selection(selection_add=[("voice", "Voice")], ondelete={"voice": "cascade"})
    whatsapp_call_log_id = fields.Many2one("whatsapp.call.log", ondelete="set null", index=True)
