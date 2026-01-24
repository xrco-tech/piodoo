# -*- coding: utf-8 -*-

import logging
from odoo import api, models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup

_logger = logging.getLogger(__name__)

MAX_RECURSION_DEPTH = 10


class WhatsAppChatbotMessage(models.Model):
    _name = 'whatsapp.chatbot.message'
    _description = 'WhatsApp Chatbot Message'
    _order = 'create_date desc'

    contact_id = fields.Many2one("whatsapp.chatbot.contact", string="Contact", required=True, tracking=True, ondelete='cascade')
    mobile_number = fields.Char(string="WhatsApp Number", tracking=True)
    step_id = fields.Many2one("whatsapp.chatbot.step", string="Chatbot Step", tracking=True)
    chatbot_id = fields.Many2one("whatsapp.chatbot", related="step_id.chatbot_id", string="Chatbot", tracking=True, store=True)
    
    # Link to whatsapp_ligth message
    wa_message_id = fields.Many2one("whatsapp.message", string="Related WhatsApp Message", tracking=True)
    
    message_plain = fields.Char(string="Plain Message", tracking=True)
    message_html = fields.Html(string="HTML Message", tracking=True)
    
    user_chatbot_answer_id = fields.Many2one("whatsapp.chatbot.answer", string="User's Chatbot Answer", tracking=True)
    
    type = fields.Selection([
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ], string="Message Type", required=True)
    
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    
    attachment_id = fields.Many2one("ir.attachment", string="Attachment", tracking=True)
    attachment_type = fields.Selection([
        ('document', 'Document'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
    ], string="Attachment Type")

    @api.depends('message_html')
    def _compute_display_name(self):
        for record in self:
            plain = Markup(record.message_html or '').striptags()
            record.display_name = plain[:60] + ('...' if len(plain) > 60 else '')
    
    @api.model
    def create(self, vals):
        message = super().create(vals)
        if message.type == "incoming":
            return self._handle_incoming_message(message, depth=0, visited_steps=set())
        elif message.type == "outgoing":
            return self._handle_outgoing_message(message, depth=0, visited_steps=set())
        return message

    def _handle_incoming_message(self, message, depth=0, visited_steps=None):
        """Handle incoming messages from users"""
        if depth > MAX_RECURSION_DEPTH:
            _logger.warning("Max recursion depth reached in _handle_incoming_message")
            return message
        visited_steps = visited_steps or set()
        
        if not message.chatbot_id:
            raise UserError("Message does not have a valid chatbot ID!")
        
        # Find next step based on current step and user answer
        if message.step_id and message.step_id.child_ids:
            message = self._process_chatbot_flow(message, depth=depth + 1, visited_steps=visited_steps)
        elif not message.step_id:
            # Start from first step
            first_step = self.env['whatsapp.chatbot.step'].search([
                ('chatbot_id', '=', message.chatbot_id.id),
                ('parent_id', '=', False)
            ], order='sequence asc', limit=1)
            if first_step:
                message.step_id = first_step.id
                if first_step.step_type in ['set_variable', 'execute_code']:
                    return self._process_variable_or_code_step(message, first_step, depth=depth + 1, visited_steps=visited_steps)
                # Send first message
                return self._send_step_message(message, first_step)
        
        self._update_contact_last_interaction(message)
        return message

    def _handle_outgoing_message(self, message, depth=0, visited_steps=None):
        """Handle outgoing messages to users"""
        # Outgoing messages are typically sent by the system
        # Process any follow-up steps if needed
        return message

    def _process_chatbot_flow(self, message, depth=0, visited_steps=None):
        """Process the chatbot flow based on user input"""
        # This will be implemented to handle step transitions
        # For now, return the message as-is
        return message

    def _process_variable_or_code_step(self, message, step, depth=0, visited_steps=None):
        """Process variable setting or code execution steps"""
        if step.step_type == 'set_variable':
            # Set variable logic
            pass
        elif step.step_type == 'execute_code':
            # Execute code
            step.execute_code(message)
        # Move to next step
        return message

    def _send_step_message(self, message, step):
        """Send a message for a chatbot step"""
        # This will integrate with whatsapp_ligth to send messages
        # For now, create an outgoing message record
        variables_dict = step._get_variables_dict(message)
        processed_body = self._replace_variables_in_message(step.body_html or '', variables_dict)
        
        return self.create({
            'contact_id': message.contact_id.id,
            'mobile_number': message.mobile_number,
            'step_id': step.id,
            'chatbot_id': step.chatbot_id.id,
            'message_html': processed_body,
            'type': 'outgoing',
        })

    def _replace_variables_in_message(self, message_html, variables_dict):
        """Replace variables in message HTML"""
        import re
        pattern = r"\{\{variables\.([\w]+)\}\}"
        def replacer(match):
            var_name = match.group(1)
            var_value = variables_dict.get(var_name)
            if var_value:
                return str(var_value.value if hasattr(var_value, 'value') else var_value)
            return f"{{{{variables.{var_name}}}}}"
        return re.sub(pattern, replacer, message_html)

    def _update_contact_last_interaction(self, message):
        """Update contact's last interaction details"""
        if message.contact_id:
            message.contact_id.write({
                'last_chatbot_id': message.chatbot_id.id,
                'last_step_id': message.step_id.id if message.step_id else False,
                'last_seen_date': fields.Datetime.now(),
            })

