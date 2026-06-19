# -*- coding: utf-8 -*-

import logging
import re
import json
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from lxml import etree
from markupsafe import Markup

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
    chatbot_channel = fields.Selection(related="chatbot_id.channel", string="Channel", store=False, readonly=True)
    
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
        ('transfer_to_agent', 'Transfer to Agent'),
        ('jump_to_flow', 'Jump to Flow/Bot'),
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
    trigger_variable_ids = fields.One2many("whatsapp.chatbot.variable.trigger", "step_id", string="Trigger Variables", tracking=True)
    
    # Buttons (reply buttons for interactive_button type — max 3 per WhatsApp spec)
    button_ids = fields.One2many("whatsapp.chatbot.step.button", "step_id", string="Buttons", tracking=True)
    # List rows (interactive_list type — grouped by section, max 10 rows per WhatsApp spec)
    list_row_ids = fields.One2many("whatsapp.chatbot.step.list.row", "step_id", string="List Rows", tracking=True)
    
    # Validation retry (question steps)
    max_retries = fields.Integer(
        string="Max Retries", default=3,
        help="Maximum validation attempts before routing to the fallback step",
    )
    fallback_step_id = fields.Many2one(
        "whatsapp.chatbot.step", string="Fallback Step",
        domain="[('chatbot_id', '=', chatbot_id)]",
        help="Step to route to after exhausting retries or unhandled input",
    )

    # Transfer to agent
    agent_partner_ids = fields.Many2many(
        "res.partner",
        "chatbot_step_agent_partner_rel", "step_id", "partner_id",
        string="Specific Agents",
        help="Override chatbot-level agents for this transfer step. Leave empty to use chatbot defaults.",
    )

    # Jump to Flow/Bot
    target_chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Target Chatbot",
        help="Chatbot to jump into. Required for jump_to_flow steps. Must match the caller's channel.",
    )
    target_step_id = fields.Many2one(
        "whatsapp.chatbot.step", string="Entry Step",
        domain="[('chatbot_id', '=', target_chatbot_id), ('parent_id', '=', False)]",
        help="Step in the target chatbot to start from. Leave empty to use the target's root step.",
    )
    jump_mode = fields.Selection([
        ('one_way', 'One-Way Jump'),
        ('subroutine', 'Subroutine (return on end)'),
    ], string="Jump Mode", default='one_way',
        help="One-way replaces the active flow. Subroutine resumes the caller when the callee ends.")
    variable_mapping_ids = fields.One2many(
        "whatsapp.chatbot.step.var.mapping", "step_id",
        string="Variable Mapping",
        help="Map caller variables to callee variables (and back, for subroutine mode).",
    )

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

    def _format_whatsapp_text(self, text):
        """
        Format WhatsApp text with styling markers to HTML.
        WhatsApp formatting:
        - *text* for bold
        - _text_ for italic
        - ~text~ for strikethrough
        - ```text``` for monospace
        - > text for blockquotes (at start of line)
        """
        if not text:
            return ''
        
        text = str(text)
        
        # Handle blockquotes first (lines starting with >)
        # Split by newlines, process each line
        lines = text.split('\n')
        formatted_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('>'):
                # Blockquote line - remove > and format
                quote_text = stripped[1:].strip()
                # Escape the quote text using Markup.escape() class method
                quote_text = Markup.escape(quote_text)
                formatted_lines.append(f'<div style="border-left: 3px solid #075E54; padding-left: 8px; margin: 4px 0; color: #666;">{quote_text}</div>')
            else:
                formatted_lines.append(line)
        text = '\n'.join(formatted_lines)
        
        # Escape HTML to prevent XSS using Markup.escape() class method
        text = Markup.escape(text)
        text = str(text)
        
        # Convert newlines to <br>
        text = text.replace('\n', '<br/>')
        
        # Handle monospace (```text```) - must be done before other formatting
        # Match triple backticks with content (non-greedy)
        text = re.sub(r'```([^`]+)```', r'<code style="background-color: rgba(0,0,0,0.1); padding: 2px 4px; border-radius: 3px; font-family: monospace; font-size: 0.9em;">\1</code>', text)
        
        # Handle strikethrough (~text~) - match tilde with content
        text = re.sub(r'~([^~\n]+)~', r'<span style="text-decoration: line-through;">\1</span>', text)
        
        # Handle bold (*text*) - must be done before italic to avoid conflicts
        # Match asterisk with content (not newlines to avoid breaking blockquotes)
        text = re.sub(r'\*([^*\n]+)\*', r'<strong>\1</strong>', text)
        
        # Handle italic (_text_) - match underscore with content
        text = re.sub(r'_([^_\n]+)_', r'<em>\1</em>', text)
        
        return Markup(text)
    
    @api.depends('body_plain')
    def _compute_body_html(self):
        """Convert plain text body to HTML with markdown formatting"""
        for rec in self:
            if rec.body_plain:
                # Format markdown and convert to HTML
                rec.body_html = self._format_whatsapp_text(rec.body_plain)
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

    @api.constrains('step_type', 'target_chatbot_id', 'target_step_id')
    def _check_jump_to_flow_target(self):
        for rec in self:
            if rec.step_type != 'jump_to_flow':
                continue
            if not rec.target_chatbot_id:
                raise ValidationError("Jump to Flow/Bot steps require a target chatbot.")
            if rec.target_chatbot_id.id == rec.chatbot_id.id and rec.target_step_id and rec.target_step_id.id == rec.id:
                raise ValidationError("A Jump step cannot target itself.")
            if rec.target_step_id and rec.target_step_id.chatbot_id.id != rec.target_chatbot_id.id:
                raise ValidationError("The entry step must belong to the target chatbot.")
            if rec.chatbot_id.channel and rec.target_chatbot_id.channel and \
                    rec.chatbot_id.channel != rec.target_chatbot_id.channel:
                raise ValidationError(
                    f"A Jump step on a {rec.chatbot_id.channel.upper()} bot cannot target a "
                    f"{rec.target_chatbot_id.channel.upper()} bot. Channels must match."
                )

    @api.constrains('step_type', 'wa_message_type', 'chatbot_id')
    def _check_interactive_only_on_whatsapp(self):
        """SMS and USSD bots cannot use interactive WhatsApp step types."""
        interactive = {'interactive_button', 'interactive_list', 'interactive_flow'}
        for rec in self:
            if rec.wa_message_type in interactive and rec.chatbot_id.channel != 'whatsapp':
                raise ValidationError(
                    f"Interactive message type '{rec.wa_message_type}' is only supported on "
                    "WhatsApp chatbots. Switch the chatbot's channel to WhatsApp or change the "
                    "message type to Non-Interactive."
                )

    @api.constrains('step_type', 'chatbot_id')
    def _check_ussd_step_types(self):
        """USSD is text-only: media-question step types are not allowed."""
        media_questions = {
            'question_document', 'question_image', 'question_video', 'question_audio',
        }
        for rec in self:
            if rec.chatbot_id.channel == 'ussd' and rec.step_type in media_questions:
                raise ValidationError(
                    f"Step type '{rec.step_type}' is not supported on USSD chatbots — "
                    "USSD is text-only. Use a question_text step instead."
                )


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


class WhatsAppChatbotStepListRow(models.Model):
    _name = 'whatsapp.chatbot.step.list.row'
    _description = 'WhatsApp Chatbot Step List Row'
    _rec_name = 'title'
    _order = 'section, sequence asc'

    step_id  = fields.Many2one("whatsapp.chatbot.step", string="Step", required=True, ondelete='cascade')
    sequence = fields.Integer(string="Sequence", default=10)
    section  = fields.Char(string="Section", help="Optional section heading to group rows under")
    row_id   = fields.Char(string="Row ID", required=True, help="Unique identifier sent back when the user picks this row")
    title    = fields.Char(string="Title", required=True)
    description = fields.Char(string="Description")


class WhatsAppChatbotStepVarMapping(models.Model):
    _name = 'whatsapp.chatbot.step.var.mapping'
    _description = 'WhatsApp Chatbot Step Variable Mapping'
    _order = 'sequence asc, id asc'

    step_id = fields.Many2one(
        "whatsapp.chatbot.step", string="Jump Step",
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string="Sequence", default=10)
    source_chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Source Chatbot",
        related="step_id.chatbot_id", store=False,
    )
    target_chatbot_id = fields.Many2one(
        "whatsapp.chatbot", string="Target Chatbot",
        related="step_id.target_chatbot_id", store=False,
    )
    source_variable_id = fields.Many2one(
        "whatsapp.chatbot.variable", string="Source Variable",
        required=True, ondelete='cascade',
        domain="[('chatbot_id', '=', source_chatbot_id)]",
    )
    target_variable_id = fields.Many2one(
        "whatsapp.chatbot.variable", string="Target Variable",
        required=True, ondelete='cascade',
        domain="[('chatbot_id', '=', target_chatbot_id)]",
    )
    direction = fields.Selection([
        ('in', 'In (caller → callee)'),
        ('out', 'Out (callee → caller)'),
        ('both', 'Both'),
    ], string="Direction", default='in', required=True,
       help="In copies on jump, Out copies back on return (subroutine only).")

    @api.constrains('source_variable_id', 'target_variable_id', 'step_id')
    def _check_chatbots_match(self):
        for rec in self:
            if rec.source_variable_id.chatbot_id.id != rec.step_id.chatbot_id.id:
                raise ValidationError("Source variable must belong to the source chatbot.")
            if rec.step_id.target_chatbot_id and rec.target_variable_id.chatbot_id.id != rec.step_id.target_chatbot_id.id:
                raise ValidationError("Target variable must belong to the target chatbot.")

