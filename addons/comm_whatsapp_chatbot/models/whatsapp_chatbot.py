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
    status = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('inactive', 'Inactive'),
    ], string='Status', default='draft', required=True, tracking=True)
    description = fields.Text(string="Description", tracking=True)
    # Delivery channel. One bot per channel — flows that should run on both
    # WhatsApp and SMS are modelled as two records.
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('ussd', 'USSD'),
        ('voice', 'Voice Call'),
    ], string='Channel', default='whatsapp', required=True, tracking=True,
       help=(
           "The messaging channel this chatbot runs on. "
           "SMS, USSD and Voice bots cannot use interactive WhatsApp step "
           "types; USSD and Voice additionally cannot use media-question "
           "step types since neither delivers media files. Voice bots are "
           "designed for live-agent assist scripts where the agent reads "
           "step bodies to the customer on a phone call."
       ))
    # Per-channel account FKs — supersede the legacy single-line sender_address.
    # Only the field matching `channel` is meaningful on a given bot; the form
    # view shows them conditionally. A bot with no account is a catch-all for
    # its channel — preserves pre-multi-number behaviour.
    whatsapp_account_id = fields.Many2one(
        'comm.whatsapp.account', string="WhatsApp Account", ondelete='restrict',
        help="The WhatsApp account this chatbot listens on. Empty = catch-all.",
    )
    sms_account_id = fields.Many2one(
        'comm.sms.account', string="SMS Account", ondelete='restrict',
        help="The SMS account this chatbot listens on. Empty = catch-all.",
    )
    ussd_account_id = fields.Many2one(
        'comm.ussd.account', string="USSD Account", ondelete='restrict',
        help="The USSD account this chatbot listens on. Empty = catch-all.",
    )

    # Compatibility back-pointer. The migration removes the column once the
    # FK fields are populated; in the meantime existing callers can still read
    # it. Computed read-only so nothing accidentally writes through it.
    sender_address = fields.Char(
        string="Sender Address",
        compute='_compute_sender_address', store=True, index='btree',
        help="Channel-specific identifier derived from the matching account: "
             "WhatsApp phone_number_id, SMS sender_id, or USSD service_code.",
    )

    @api.depends(
        'channel',
        'whatsapp_account_id.phone_number_id',
        'sms_account_id.sender_id',
        'ussd_account_id.service_code',
    )
    def _compute_sender_address(self):
        for rec in self:
            if rec.channel == 'whatsapp':
                rec.sender_address = rec.whatsapp_account_id.phone_number_id or ''
            elif rec.channel == 'sms':
                rec.sender_address = rec.sms_account_id.sender_id or ''
            elif rec.channel == 'ussd':
                rec.sender_address = rec.ussd_account_id.service_code or ''
            else:
                rec.sender_address = ''
    
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

    # active users only includes real (non-simulator) contacts. Domain on the
    # One2many keeps both the form list and the smart-button count in sync.
    chatbot_contact_ids = fields.One2many(
        "whatsapp.chatbot.contact", "last_chatbot_id",
        string="Active Users", tracking=True,
        domain=[('is_simulator', '=', False)],
    )
    chatbot_contact_count = fields.Integer(string="Active Users", compute="_compute_contact_count", store=True)
    # Every contact that has ever entered this chatbot (regardless of where they
    # are now). Populated at trigger match / jump entry; backfilled from
    # whatsapp.chatbot.message history at install time.
    historical_contact_count = fields.Integer(
        string="Total Users", compute="_compute_historical_contact_count", store=False,
        help="Number of contacts who have ever entered this chatbot, including those now in another bot.",
    )
    chatbot_message_ids = fields.One2many(
        "whatsapp.chatbot.message", "chatbot_id",
        string="Messages", tracking=True,
        domain=[('is_simulator', '=', False)],
    )
    chatbot_message_count = fields.Integer(string="Messages", compute="_compute_message_count", store=True)

    forward_to_external_agent = fields.Boolean(string="Enable Forwarding to External Agent?", default=False, tracking=True)
    external_agent_partner_ids = fields.Many2many("res.partner", string="External Agents", tracking=True)

    global_interrupt_ids = fields.One2many(
        "whatsapp.chatbot.global.interrupt", "chatbot_id",
        string="Global Interrupt Keywords", tracking=True,
    )
    
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

    def _compute_historical_contact_count(self):
        # search_count on the inverse of contact.chatbot_ids — counts every
        # real (non-simulator) contact whose M2M includes this chatbot.
        Contact = self.env['whatsapp.chatbot.contact'].sudo()
        for rec in self:
            rec.historical_contact_count = Contact.search_count([
                ('chatbot_ids', 'in', rec.id),
                ('is_simulator', '=', False),
            ])

    def action_publish(self):
        for rec in self:
            rec.status = 'published'

    def action_deactivate(self):
        for rec in self:
            rec.status = 'inactive'

    def action_reset_to_draft(self):
        for rec in self:
            rec.status = 'draft'

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
            'view_mode': 'list,form',
            'domain': [('last_chatbot_id', '=', self.id), ('is_simulator', '=', False)],
        }

    def action_view_historical_users(self):
        self.ensure_one()
        return {
            'name': _('Total Users'),
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.chatbot.contact',
            'view_mode': 'list,form',
            'domain': [('chatbot_ids', 'in', self.id), ('is_simulator', '=', False)],
        }

    def action_view_messages(self):
        self.ensure_one()
        return {
            'name': _('Messages'),
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.chatbot.message',
            'view_mode': 'list,form',
            'domain': [('chatbot_id', '=', self.id), ('is_simulator', '=', False)],
        }

    def action_open_agent_workspace(self):
        """Launch the OWL Agent Workspace for live calls. Only meaningful on
        voice channel — the smart button visibility enforces that."""
        self.ensure_one()
        return {
            'type':   'ir.actions.client',
            'tag':    'comm_whatsapp_chatbot.agent_workspace',
            'name':   f'Workspace — {self.name}',
            'params': {
                'chatbot_id':   self.id,
                'chatbot_name': self.name,
            },
        }

    def action_view_step_hierarchy(self):
        """Open the native OWL flow designer for this chatbot"""
        self.ensure_one()
        return {
            'type':   'ir.actions.client',
            'tag':    'comm_whatsapp_chatbot.chatbot_flow',
            'name':   f'Flow — {self.name}',
            'params': {
                'chatbot_id':   self.id,
                'chatbot_name': self.name,
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

