# -*- coding: utf-8 -*-

import logging
import re
import json
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from lxml import etree

_logger = logging.getLogger(__name__)


class WhatsAppChatbotStep(models.Model):
    _name = 'whatsapp.chatbot.step'
    _description = 'WhatsApp Chatbot Step'
    _order = 'parent_path, sequence asc'
    _parent_name = 'parent_id'
    _parent_store = True

    # Hierarchy fields
    parent_id = fields.Many2one("whatsapp.chatbot.step", string="Parent", ondelete='cascade')
    child_ids = fields.One2many("whatsapp.chatbot.step", "parent_id", string="Children")
    parent_path = fields.Char(index=True, unaccent=False)

    # Computed fields for hierarchy
    hierarchy_path = fields.Char(string="Hierarchy Path", compute="_compute_hierarchy_path", store=True)
    display_name_hierarchy = fields.Char(string="Display Name", compute="_compute_display_name_hierarchy", store=True)
    child_count = fields.Integer(string="Children", compute="_compute_child_count", store=True)
    hierarchy_level = fields.Integer(string="Level", compute="_compute_hierarchy_level", store=True)

    # Basic fields
    name = fields.Char(string="Step", tracking=True, required=True)
    sequence = fields.Integer(string="Sequence", tracking=True, default=10)
    chatbot_id = fields.Many2one("whatsapp.chatbot", string="Chatbot", required=True, tracking=True, ondelete='cascade')
    
    step_type = fields.Selection([
        ('message', 'Message'),
        ('question_text', 'Question (Text)'),
        ('question_numeric', 'Question (Numeric)'),
        ('question_phone', 'Question (Phone)'),
        ('question_email', 'Question (Email)'),
        ('question_date', 'Question (Date)'),
        ('question_document', 'Question (Document)'),
        ('question_image', 'Question (Image)'),
        ('question_video', 'Question (Video)'),
        ('question_audio', 'Question (Audio)'),
        ('question_interactive', 'Question (Interactive)'),
        ('set_variable', 'Set Variable'),
        ('execute_code', 'Execute Code'),
        ('end_flow', 'End Flow'),
    ], string="Step Type", required=True, default='message')
    
    # Message content
    wa_message_type = fields.Selection([
        ('non_interactive', 'Non-Interactive'),
        ('interactive_button', 'Interactive Reply Buttons'),
        ('interactive_list', 'Interactive List'),
        ('interactive_flow', 'Interactive Flow'),
    ], string="WA Message Type", default='non_interactive')
    
    body_plain = fields.Text(string="Body (Plain Text)", tracking=True)
    body_html = fields.Html(string="Body (HTML)", tracking=True, compute="_compute_body_html", store=False)
    list_button_text = fields.Char(string='List Button Text', default="See all options")
    
    # Header and footer
    header_type = fields.Selection([
        ('text', 'Text'),
        ('document', 'Document'),
        ('image', 'Image'),
        ('video', 'Video'),
    ], string="Header Type")
    header_text = fields.Char(string='Header Text')
    header = fields.Json(string="Header")
    footer = fields.Char(string="Footer")
    
    # Flow integration
    flow_id = fields.Many2one("whatsapp.flow", string="Flow", domain="[('status', '=', 'PUBLISHED')]")
    flow_uid = fields.Char(related="flow_id.flow_id_meta", string="Flow ID", readonly=True)
    screen_id = fields.Char(string="Entry Screen ID", help="Screen ID to navigate to")
    screen_payload_data = fields.Json(string="Screen Payload")
    flow_cta = fields.Char(string="Click To Action Text")
    flow_action = fields.Selection([
        ('navigate', 'Navigate'),
        ('data_exchange', 'Data Exchange'),
    ], string="Flow Action", default='navigate')
    
    # Variables
    variable_id = fields.Many2one("whatsapp.chatbot.variable", string="Variable", tracking=True)
    variable_data_source = fields.Selection([
        ('static', 'Static'),
        ('answer', 'Answer'),
        ('variable', 'Variable'),
    ], string="Data Source", default='static')
    source_step_id = fields.Many2one("whatsapp.chatbot.step", string="Source Step", tracking=True)
    source_variable_id = fields.Many2one("whatsapp.chatbot.variable", string="Source Variable", tracking=True)
    variable_value = fields.Char(string="Variable Value", tracking=True)
    
    # Answer handling
    answer_data_type = fields.Selection([
        ('text', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('date', 'Date'),
        ('boolean', 'Boolean'),
        ('document', 'Document'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
    ], string="Answer Data Type", default='text')
    trigger_answer_ids = fields.Many2many("whatsapp.chatbot.answer", string="Trigger Answers", tracking=True)
    
    # Buttons
    button_ids = fields.Many2many("whatsapp.chatbot.step.button", string="Buttons", tracking=True)
    
    # Code execution
    code = fields.Text(string="Executable Code", help="Write Python code to be executed.")
    
    # Attachments
    attachment_id = fields.Many2one("ir.attachment", string="Attachment", tracking=True)
    attachment_source = fields.Selection([
        ('static', 'Static'),
        ('chatbot_data', 'Chatbot Data'),
    ], string="Attachment Source", default='static')
    
    # Message tracking
    step_messages_ids = fields.One2many("whatsapp.chatbot.message", "step_id", string="Step Messages")
    step_messages_count = fields.Integer(string="Step Messages Count", compute="_compute_step_messages_count")
   
    @api.depends('step_messages_ids')
    def _compute_step_messages_count(self):
        for rec in self:
            rec.step_messages_count = len(rec.step_messages_ids.filtered(lambda m: m.type == 'outgoing'))

    @api.depends('name', 'parent_id', 'parent_id.hierarchy_path')
    def _compute_hierarchy_path(self):
        for rec in self:
            if rec.parent_id:
                rec.hierarchy_path = f"{rec.parent_id.hierarchy_path} > {rec.name}" if rec.parent_id.hierarchy_path else rec.name
            else:
                rec.hierarchy_path = rec.name

    @api.depends('name', 'step_type', 'hierarchy_path')
    def _compute_display_name_hierarchy(self):
        for rec in self:
            rec.display_name_hierarchy = f"{rec.hierarchy_path} ({rec.step_type})"

    @api.depends('child_ids')
    def _compute_child_count(self):
        for rec in self:
            rec.child_count = len(rec.child_ids)

    @api.depends('parent_id', 'parent_id.hierarchy_level')
    def _compute_hierarchy_level(self):
        for rec in self:
            if rec.parent_id:
                rec.hierarchy_level = rec.parent_id.hierarchy_level + 1
            else:
                rec.hierarchy_level = 0

    @api.depends('body_plain')
    def _compute_body_html(self):
        """Convert plain text body to HTML"""
        for rec in self:
            if rec.body_plain:
                # Simple conversion: preserve line breaks
                rec.body_html = rec.body_plain.replace('\n', '<br/>')
            else:
                rec.body_html = False

    def _get_variables_dict(self, record):
        """Get a dictionary of variables for the contact"""
        variables_dict = {}
        contact_variables = self.env['whatsapp.chatbot.value'].search([
            ('contact_id', '=', record.contact_id.id),
            ('chatbot_id', '=', record.chatbot_id.id), 
        ])
        for variable in contact_variables:
            variables_dict[variable.variable_id.name] = variable
        return variables_dict

    def execute_code(self, record):
        """Executes the stored Python code and captures the result."""
        variables = self._get_variables_dict(record)
        local_env = {
            'self': self, 
            'env': self.env, 
            'record': record, 
            'variables': variables, 
            '_logger': _logger, 
            'json': json
        }
        try:
            exec(self.code, {}, local_env)
            result = local_env.get("result", "No result returned.")
        except Exception as e:
            result = f"Error: {str(e)}"
        return result

    @api.constrains('name')
    def _check_name_characters(self):
        for rec in self:
            if not re.match(r'^[A-Za-z\s-]+$', rec.name):
                raise ValidationError("The name can only contain alphabets (both uppercase and lowercase), spaces, and dashes.")


class WhatsAppChatbotStepButton(models.Model):
    _name = 'whatsapp.chatbot.step.button'
    _description = 'WhatsApp Chatbot Step Button'
    _rec_name = 'title'
    _order = 'sequence asc'
    
    step_id = fields.Many2one("whatsapp.chatbot.step", string="Chatbot Step", required=True, tracking=True, ondelete='cascade')
    chatbot_id = fields.Many2one("whatsapp.chatbot", related="step_id.chatbot_id", string="Chatbot", required=True, tracking=True)
    sequence = fields.Integer(string="Sequence", tracking=True, default=10)
    button_id = fields.Char(string="Button ID", tracking=True, required=True)
    title = fields.Char(string="Title", tracking=True, required=True)
    description = fields.Char(string="Description", tracking=True)

