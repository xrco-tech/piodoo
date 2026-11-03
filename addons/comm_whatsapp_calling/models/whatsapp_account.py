# -*- coding: utf-8 -*-

from odoo import fields, models


class CommWhatsAppAccountCalling(models.Model):
    _inherit = "comm.whatsapp.account"

    call_auto_record = fields.Boolean(
        string="Auto-record calls", default=False,
        help="Start recording each WhatsApp call on this number as soon as it "
             "connects. Agents can still stop and start recording themselves.")
