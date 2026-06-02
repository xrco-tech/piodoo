# -*- coding: utf-8 -*-

from odoo import models, fields


class WhatsAppChatbotGlobalInterrupt(models.Model):
    _name = 'whatsapp.chatbot.global.interrupt'
    _description = 'WhatsApp Chatbot Global Interrupt Keyword'
    _order = 'sequence asc'

    chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Chatbot", required=True,
        ondelete='cascade',
        default=lambda self: self.env.context.get('default_chatbot_id'),
    )
    sequence = fields.Integer(string="Sequence", default=10)
    keyword = fields.Char(
        string="Keyword", required=True,
        help="User message that triggers this interrupt (case-insensitive, partial match)",
    )
    action = fields.Selection([
        ('goto_step',       'Go to Step'),
        ('transfer_agent',  'Transfer to Agent'),
        ('end_flow',        'End Flow'),
    ], string="Action", required=True, default='goto_step')
    target_step_id = fields.Many2one(
        "whatsapp.chatbot.step", string="Target Step",
        domain="[('chatbot_id', '=', chatbot_id)]",
    )
    response_message = fields.Char(
        string="Response Message",
        help="Optional message sent to the user when this interrupt fires",
    )
