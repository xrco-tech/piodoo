# -*- coding: utf-8 -*-

from odoo import fields, models


class WhatsAppCallLog(models.Model):
    _inherit = "whatsapp.call.log"

    # Populated by the Agent Workspace when a call is dialled from a
    # voice-channel chatbot session. Lets the chatbot form show a per-
    # chatbot call history via a smart button.
    chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Chatbot", index=True,
        ondelete="set null",
        help="Voice-channel chatbot that initiated this call, when known.",
    )
