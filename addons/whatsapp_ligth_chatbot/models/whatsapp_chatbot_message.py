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
    
    @api.model
    def process_incoming_webhook_message(self, wa_message, webhook_message, value_data, entry_data):
        """
        Process incoming webhook message through chatbot system.
        This method is called from the main webhook controller.
        
        :param wa_message: The created whatsapp.message record
        :param webhook_message: The original webhook message data
        :param value_data: The value object containing metadata and contacts
        :param entry_data: The entry object containing business account info
        """
        try:
            if not wa_message or not wa_message.is_incoming:
                return
            
            ChatbotContact = self.env['whatsapp.chatbot.contact'].sudo()
            Chatbot = self.env['whatsapp.chatbot'].sudo()
            Partner = self.env['res.partner'].sudo()
            
            # Extract message info
            message_id = webhook_message.get('id')
            wa_id = webhook_message.get('from')
            message_body = wa_message.message_body or ''
            
            # Find or create partner
            contacts = value_data.get('contacts', [])
            contact_data = contacts[0] if contacts else {}
            partner = self._find_or_create_partner(wa_id, contact_data)
            
            if not partner:
                _logger.warning(f"Could not find or create partner for {wa_id}")
                return
            
            # Find or create chatbot contact
            chatbot_contact = ChatbotContact.search([('partner_id', '=', partner.id)], limit=1)
            if not chatbot_contact:
                chatbot_contact = ChatbotContact.create({
                    'partner_id': partner.id,
                })
            
            # Extract message text for trigger matching
            message_text = message_body.strip() if message_body else ''
            
            # Check if contact is actively engaged in a chatbot conversation
            chatbot = None
            if chatbot_contact.last_chatbot_id and chatbot_contact.last_step_id:
                # Check if the last step is not an end_flow step
                if chatbot_contact.last_step_id.step_type != 'end_flow':
                    chatbot = chatbot_contact.last_chatbot_id
                    _logger.info(f"Contact is actively engaged with chatbot: {chatbot.name}")
            
            # If not actively engaged, check for trigger words
            if not chatbot and message_text:
                # Search for matching trigger (case-insensitive)
                matching_trigger = self.env['whatsapp.chatbot.trigger'].sudo().search([
                    ('name', '=ilike', message_text)
                ], limit=1)
                
                if matching_trigger:
                    chatbot = matching_trigger.chatbot_id
                    _logger.info(f"Trigger '{message_text}' matched to chatbot: {chatbot.name}")
                    # Clear all variables when starting a new chatbot flow
                    chatbot_contact.variable_value_ids.unlink()
                    # Reset last step
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                    })
            
            # If still no chatbot, use the last active chatbot or first available
            if not chatbot:
                chatbot = chatbot_contact.last_chatbot_id
                if not chatbot:
                    # Find first available chatbot
                    chatbot = Chatbot.search([], limit=1)
                    if chatbot:
                        chatbot_contact.write({'last_chatbot_id': chatbot.id})
            
            if not chatbot:
                _logger.warning("No chatbot found to process message")
                return
            
            # Find first step of chatbot (will be set by _handle_incoming_message if not set)
            first_step = self.env['whatsapp.chatbot.step'].sudo().search([
                ('chatbot_id', '=', chatbot.id),
                ('parent_id', '=', False)
            ], order='sequence asc', limit=1)
            
            # Create chatbot message record
            # chatbot_id is a related field from step_id.chatbot_id, so we'll let _handle_incoming_message set it
            chatbot_message = self.create({
                'contact_id': chatbot_contact.id,
                'mobile_number': wa_id,
                'wa_message_id': wa_message.id,
                'message_plain': message_body,
                'message_html': message_body,  # Simple conversion, can be enhanced
                'type': 'incoming',
                'step_id': first_step.id if first_step else False,
            })
            
            _logger.info(f"Created chatbot message: {chatbot_message.id}")
            
        except Exception as e:
            _logger.error(f"Error processing chatbot message: {e}", exc_info=True)
    
    def _find_or_create_partner(self, wa_id, contact_data):
        """
        Find or create a partner based on WhatsApp ID.
        
        :param wa_id: WhatsApp ID
        :param contact_data: Contact data from webhook
        :return: Partner record
        """
        try:
            # Try to find by mobile/phone
            phone_number = contact_data.get('wa_id') or wa_id
            partner = self.env['res.partner'].sudo().search([
                '|',
                ('phone', '=', phone_number),
                ('mobile', '=', phone_number)
            ], limit=1)
            
            if not partner:
                # Create new partner
                name = contact_data.get('profile', {}).get('name', f"WhatsApp Contact {phone_number}")
                partner = self.env['res.partner'].sudo().create({
                    'name': name,
                    'mobile': phone_number,
                    'is_company': False,
                })
                _logger.info(f"Created new partner: {partner.id} for {phone_number}")
            
            return partner
            
        except Exception as e:
            _logger.error(f"Error finding/creating partner: {e}")
            return False

