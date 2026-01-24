# -*- coding: utf-8 -*-

import logging
from odoo import api, models, fields

_logger = logging.getLogger(__name__)


class WhatsAppChatbotContact(models.Model):
    _name = 'whatsapp.chatbot.contact'
    _description = 'WhatsApp Chatbot Contact'

    partner_id = fields.Many2one("res.partner", string="Partner", required=True, tracking=True)
    name = fields.Char(string="Name", related="partner_id.name", tracking=True, store=True)
    mobile_number = fields.Char(string="WhatsApp Number", related="partner_id.mobile", tracking=True, store=True)
    
    chatbot_ids = fields.Many2many("whatsapp.chatbot", string="Chatbots", tracking=True)
    message_ids = fields.One2many("whatsapp.chatbot.message", "contact_id", string="Messages", tracking=True, ondelete="cascade")
    last_message = fields.Html(string="Last Message", tracking=True)
    
    variable_value_ids = fields.One2many("whatsapp.chatbot.value", "contact_id", string="Variable Values", tracking=True, ondelete="cascade")
    
    last_chatbot_id = fields.Many2one("whatsapp.chatbot", string="Last Chatbot", tracking=True)
    last_step_id = fields.Many2one("whatsapp.chatbot.step", string="Chatbot Step", tracking=True)
    last_seen_date = fields.Datetime('Last Seen Date')
    
    active_agent = fields.Selection([
        ('flow_agent', 'Flow Agent'),
        ('ai_agent', 'AI Agent'),
        ('human_agent', 'Human Agent'),
    ], string="Active Agent", default="flow_agent")

