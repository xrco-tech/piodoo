# -*- coding: utf-8 -*-

import logging
import re
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError, UserError
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)


class WhatsAppChatbot(models.Model):
    _name = 'whatsapp.chatbot'
    _description = 'WhatsApp Chatbot'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Name", tracking=True, required=True)
    description = fields.Text(string="Description", tracking=True)
    
    # Steps and flow
    step_ids = fields.One2many("whatsapp.chatbot.step", "chatbot_id", string="Steps", tracking=True)
    bot_trigger_ids = fields.Many2many("whatsapp.chatbot.trigger", string="Chatbot Triggers", tracking=True)
    bot_variable_ids = fields.One2many("whatsapp.chatbot.variable", "chatbot_id", string="Variables", tracking=True)
    
    # Default messages
    default_confusion_message = fields.Text(string="Default Confusion Message", tracking=True)
    default_error_message = fields.Text(string="Default Error Message", tracking=True)

    # Context building resources
    context_pdf = fields.Many2one("ir.attachment", "Context PDF", tracking=True)
    context_url = fields.Char("Context Website/URL", tracking=True)
    context_data = fields.Text("Context Data", tracking=True)

    # AI Agent settings
    ai_agent_prompt_text = fields.Text("AI Context Prompt", tracking=True)
    ai_agent_header = fields.Char("AI Message Header", tracking=True)
    ai_agent_footer = fields.Char("AI Message Footer", tracking=True)
    ai_agent_rtc_button_label = fields.Char("Return-to-Chat Label", tracking=True)

    # Computed fields for smart buttons
    step_count = fields.Integer(string="Steps", compute="_compute_step_count", store=True)
    root_step_ids = fields.One2many("whatsapp.chatbot.step", "chatbot_id", string="Root Steps", 
                                   domain=[('parent_id', '=', False)])

    preview_url = fields.Char(string="Preview URL", compute='_compute_preview_url', tracking=True)

    chatbot_contact_ids = fields.One2many("whatsapp.chatbot.contact", "last_chatbot_id", string="Active Users", tracking=True)
    chatbot_contact_count = fields.Integer(string="Active Users", compute="_compute_contact_count", store=True)
    chatbot_message_ids = fields.One2many("whatsapp.chatbot.message", "chatbot_id", string="Messages", tracking=True)
    chatbot_message_count = fields.Integer(string="Messages", compute="_compute_message_count", store=True)

    forward_to_external_agent = fields.Boolean(string="Enable Forwarding to External Agent?", default=False, tracking=True)
    external_agent_partner_ids = fields.Many2many("res.partner", string="External Agents", tracking=True)
    
    @api.depends('step_ids')
    def _compute_step_count(self):
        for rec in self:
            rec.step_count = len(rec.step_ids)

    @api.depends('chatbot_contact_ids')
    def _compute_contact_count(self):
        for rec in self:
            rec.chatbot_contact_count = len(rec.chatbot_contact_ids)

    @api.depends('chatbot_message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.chatbot_message_count = len(rec.chatbot_message_ids)

    def get_root_steps(self):
        """Get root steps (steps without parent) for this chatbot"""
        self.ensure_one()
        return self.step_ids.filtered(lambda s: not s.parent_id)

    def action_view_active_users(self):
        self.ensure_one()
        return {
            'name': _('Active Users'),
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.chatbot.contact',
            'view_mode': 'tree,form',
            'domain': [('last_chatbot_id', '=', self.id)],
        }

    def action_view_messages(self):
        self.ensure_one()
        return {
            'name': _('Messages'),
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.chatbot.message',
            'view_mode': 'tree,form',
            'domain': [('chatbot_id', '=', self.id)],
        }

    def action_view_step_hierarchy(self):
        """Open the step hierarchy view for this chatbot"""
        self.ensure_one()
        return {
            'name': f'Step Hierarchy - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.chatbot.step',
            'view_mode': 'tree,form',
            'domain': [('chatbot_id', '=', self.id)],
            'context': {
                'default_chatbot_id': self.id,
                'search_default_filter_root_steps': 1,
            },
        }

    def _compute_preview_url(self):
        for rec in self:
            rec.preview_url = f"/chatbot/steps/{rec.id}"

    @api.constrains('name')
    def _check_name_characters(self):
        for rec in self:
            if not re.match(r'^[A-Za-z\s-]+$', rec.name):
                raise ValidationError("The name can only contain alphabets (both uppercase and lowercase), spaces, and dashes.")
            
    @api.constrains('context_url')
    def _is_valid_url(self):
        for rec in self:
            if rec.context_url:
                try:
                    urlparse(rec.context_url)
                except:
                    raise ValidationError("Please enter a valid URL, e.g. https://www.example.com/about-us")
    
    @api.model
    def create(self, vals):
        res = super(WhatsAppChatbot, self).create(vals)
        res.preview_url = f"/chatbot/steps/{res.id}"
        return res


class WhatsAppChatbotTrigger(models.Model):
    _name = 'whatsapp.chatbot.trigger'
    _description = 'WhatsApp Chatbot Trigger'

    name = fields.Char(string="Trigger", tracking=True, required=True)
    chatbot_id = fields.Many2one("whatsapp.chatbot", string="Chatbot", required=True, tracking=True)

