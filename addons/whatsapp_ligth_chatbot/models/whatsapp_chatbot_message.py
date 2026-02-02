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
    # Make chatbot_id a regular Many2one instead of a related field so it's always available
    chatbot_id = fields.Many2one("whatsapp.chatbot", string="Chatbot", required=True, tracking=True)
    
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
        # Do not run _handle_incoming_message here: sending is done in
        # process_incoming_webhook_message after create(). That way only the
        # request that actually creates the record sends; duplicate webhook
        # deliveries that hit "existing_chatbot_message" return early and never send.
        if message.type == "outgoing":
            return self._handle_outgoing_message(message, depth=0, visited_steps=set())
        return message

    def _handle_incoming_message(self, message, depth=0, visited_steps=None, from_trigger=True):
        """Handle incoming messages from users.
        from_trigger: True when user sent trigger word (send this step); False when replying (process reply, don't resend).
        """
        if depth > MAX_RECURSION_DEPTH:
            _logger.warning("Max recursion depth reached in _handle_incoming_message")
            return message
        visited_steps = visited_steps or set()
        
        # Ensure chatbot_id is set; if missing but step_id is present, derive it
        if not message.chatbot_id and message.step_id and message.step_id.chatbot_id:
            message.chatbot_id = message.step_id.chatbot_id
        if not message.chatbot_id:
            _logger.error("Incoming chatbot message has no chatbot_id; skipping processing.")
            return message
        
        # Find next step based on current step and user answer
        if message.step_id:
            # User replying (actively engaged): process their answer, don't resend the same step
            if not from_trigger:
                return self._process_chatbot_flow(message, depth=depth + 1, visited_steps=visited_steps)
            # From trigger: send this step's message (first step)
            if message.step_id.step_type in ['set_variable', 'execute_code']:
                return self._process_variable_or_code_step(message, message.step_id, depth=depth + 1, visited_steps=visited_steps)
            return self._send_step_message(message, message.step_id)
        elif not message.step_id:
            # Start from first step
            first_step = self.env['whatsapp.chatbot.step'].search([
                ('chatbot_id', '=', message.chatbot_id.id),
                ('parent_id', '=', False)
            ], order='sequence asc', limit=1)
            if first_step:
                _logger.info(f"Starting chatbot flow with first step: {first_step.name} (ID: {first_step.id})")
                message.step_id = first_step.id
                if first_step.step_type in ['set_variable', 'execute_code']:
                    return self._process_variable_or_code_step(message, first_step, depth=depth + 1, visited_steps=visited_steps)
                # Send first message
                return self._send_step_message(message, first_step)
            else:
                _logger.warning(f"No first step found for chatbot {message.chatbot_id.name}")
        
        self._update_contact_last_interaction(message)
        return message

    def _handle_outgoing_message(self, message, depth=0, visited_steps=None):
        """Handle outgoing messages to users"""
        # Outgoing messages are typically sent by the system
        # Process any follow-up steps if needed
        return message

    def _process_chatbot_flow(self, message, depth=0, visited_steps=None):
        """
        Process user reply: advance to next step (first child by sequence) and send it.
        For question_text / message steps, any reply goes to the first child step.
        """
        if depth > MAX_RECURSION_DEPTH:
            _logger.warning("Max recursion depth reached in _process_chatbot_flow")
            return message
        visited_steps = visited_steps or set()
        current_step = message.step_id
        if not current_step:
            self._update_contact_last_interaction(message)
            return message
        if current_step.id in visited_steps:
            _logger.warning(f"Already visited step {current_step.id}, stopping")
            return message
        visited_steps.add(current_step.id)
        # Next step = first child by sequence (for question_text / message, any reply goes to next)
        children = current_step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
        if not children:
            self._update_contact_last_interaction(message)
            return message
        next_step = children[0]
        if next_step.step_type == 'end_flow':
            message.contact_id.write({
                'last_chatbot_id': message.chatbot_id.id,
                'last_step_id': next_step.id,
                'last_seen_date': fields.Datetime.now(),
            })
            return message
        if next_step.step_type in ['set_variable', 'execute_code']:
            return self._process_variable_or_code_step(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        _logger.info(f"Advancing from step {current_step.name} to {next_step.name} (ID: {next_step.id})")
        return self._send_step_message(message, next_step)

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
        try:
            from markupsafe import Markup
            
            _logger.info(f"Sending message for step: {step.name} (ID: {step.id}, Type: {step.step_type})")
            
            # Get message body (prefer plain text, fallback to HTML)
            body_text = step.body_plain or ''
            if not body_text and step.body_html:
                # Extract plain text from HTML
                body_text = Markup(step.body_html).striptags()
            
            if not body_text:
                _logger.warning(f"Step {step.id} ({step.name}) has no message body (body_plain or body_html) to send")
                return message
            
            # Replace variables in message
            variables_dict = step._get_variables_dict(message)
            processed_body = self._replace_variables_in_message(body_text, variables_dict)
            
            if not processed_body or not processed_body.strip():
                _logger.warning(f"Step {step.id} processed message body is empty after variable replacement")
                return message
            
            _logger.info(f"Processed message body: {processed_body[:100]}...")
            
            # Get phone number and phone_number_id from the original WhatsApp message
            phone_number = message.mobile_number
            phone_number_id = None
            context_message_id = None
            
            if message.wa_message_id:
                phone_number_id = message.wa_message_id.phone_number_id
                context_message_id = message.wa_message_id.message_id
            
            # Send message via WhatsApp API
            WhatsAppMessage = self.env['whatsapp.message'].sudo()
            result = WhatsAppMessage.send_whatsapp_message(
                recipient_phone=phone_number,
                message_text=processed_body,
                phone_number_id=phone_number_id,
                context_message_id=context_message_id
            )
            
            if result.get('success'):
                _logger.info(f"Chatbot message sent successfully: {result.get('message_id')}")
                
                # Create outgoing chatbot message record
                outgoing_message = self.create({
                    'contact_id': message.contact_id.id,
                    'mobile_number': phone_number,
                    'step_id': step.id,
                    'chatbot_id': step.chatbot_id.id,
                    'message_html': processed_body,
                    'message_plain': processed_body,
                    'type': 'outgoing',
                })
                
                # Update contact's last step
                self._update_contact_last_interaction(outgoing_message)
                
                # Auto-advance: if this step has exactly one child that is not end_flow,
                # send it immediately (e.g. message → question so user gets both in sequence)
                children = step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                if len(children) == 1 and children[0].step_type != 'end_flow':
                    _logger.info(f"Auto-advancing to next step: {children[0].name} (ID: {children[0].id})")
                    return self._send_step_message(message, children[0])
                
                return outgoing_message
            else:
                _logger.error(f"Failed to send chatbot message: {result.get('error')}")
                return message
                
        except Exception as e:
            _logger.error(f"Error sending step message: {e}", exc_info=True)
            return message

    def _replace_variables_in_message(self, message_text, variables_dict):
        """Replace variables in message text (plain text or HTML)"""
        import re
        pattern = r"\{\{variables\.([\w]+)\}\}"
        def replacer(match):
            var_name = match.group(1)
            var_value = variables_dict.get(var_name)
            if var_value:
                # Get the actual value from the variable value record
                if hasattr(var_value, 'value'):
                    return str(var_value.value or '')
                return str(var_value)
            return f"{{{{variables.{var_name}}}}}"
        return re.sub(pattern, replacer, message_text or '')

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
            
            # Track whether we're starting from a trigger (send first step) or continuing (process reply)
            from_trigger = False
            chatbot = None
            if chatbot_contact.last_chatbot_id and chatbot_contact.last_step_id:
                # Check if the last step is not an end_flow step
                if chatbot_contact.last_step_id.step_type != 'end_flow':
                    chatbot = chatbot_contact.last_chatbot_id
                    _logger.info(f"Contact is actively engaged with chatbot: {chatbot.name}")
            
            # If not actively engaged, check for trigger words
            if not chatbot and message_text:
                # Search for matching trigger (exact case-insensitive match)
                # Use uppercase comparison like whatsapp_custom does for exact matching
                matching_trigger = self.env['whatsapp.chatbot.trigger'].sudo().search([
                    ('name', '=', message_text.upper())
                ], limit=1)
                
                if matching_trigger:
                    from_trigger = True
                    chatbot = matching_trigger.chatbot_id
                    _logger.info(f"Trigger '{message_text}' matched to chatbot: {chatbot.name}")
                    # Clear all variables when starting a new chatbot flow
                    chatbot_contact.variable_value_ids.unlink()
                    # Reset last step
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                    })
                else:
                    # No trigger matched - don't assign a chatbot
                    # Only process messages that match triggers or are already in a conversation
                    _logger.info(f"No trigger matched for message '{message_text}'. Skipping chatbot processing.")
                    return
            
            # Only continue if we have a chatbot (either from active conversation or trigger match)
            if not chatbot:
                _logger.warning("No chatbot found to process message")
                return
            
            # If user is engaged but sends the trigger word again, restart the flow (from_trigger=True)
            if chatbot and message_text and not from_trigger:
                matching_trigger = self.env['whatsapp.chatbot.trigger'].sudo().search([
                    ('name', '=', message_text.upper()),
                    ('chatbot_id', '=', chatbot.id),
                ], limit=1)
                if matching_trigger:
                    from_trigger = True
                    _logger.info(f"Trigger '{message_text}' while engaged: restarting flow for {chatbot.name}")
                    chatbot_contact.variable_value_ids.unlink()
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                    })
            
            # Lock this WhatsApp message row so only one webhook delivery creates and sends.
            # The second delivery will block here until the first commits, then see existing.
            self.env.cr.execute(
                "SELECT id FROM whatsapp_message WHERE id = %s FOR UPDATE",
                (wa_message.id,),
            )
            if not self.env.cr.rowcount:
                return
            
            # Check if chatbot message already exists for this WhatsApp message
            # This prevents duplicate chatbot messages from the same WhatsApp message
            existing_chatbot_message = self.sudo().search([
                ('wa_message_id', '=', wa_message.id),
                ('type', '=', 'incoming')
            ], limit=1)
            
            if existing_chatbot_message:
                _logger.info(f"Chatbot message already exists for WhatsApp message {wa_message.id} (chatbot message ID: {existing_chatbot_message.id}). Skipping duplicate creation.")
                return existing_chatbot_message
            
            # Step to use: first step when from trigger, last step when actively engaged (reply)
            if from_trigger:
                step_to_use = self.env['whatsapp.chatbot.step'].sudo().search([
                    ('chatbot_id', '=', chatbot.id),
                    ('parent_id', '=', False)
                ], order='sequence asc', limit=1)
            else:
                step_to_use = chatbot_contact.last_step_id
            
            # Create chatbot message record with duplicate handling for race conditions
            try:
                chatbot_message = self.create({
                    'contact_id': chatbot_contact.id,
                    'mobile_number': wa_id,
                    'chatbot_id': chatbot.id,
                    'wa_message_id': wa_message.id,
                    'message_plain': message_body,
                    'message_html': message_body,  # Simple conversion, can be enhanced
                    'type': 'incoming',
                    'step_id': step_to_use.id if step_to_use else False,
                })
                _logger.info(f"Created chatbot message: {chatbot_message.id}")
                # Send only here (not in create()) so duplicate webhook deliveries
                # that return existing_chatbot_message never send.
                # When from_trigger=True we send the step; when False (reply) we process flow, don't resend.
                chatbot_message = self._handle_incoming_message(
                    chatbot_message, depth=0, visited_steps=set(), from_trigger=from_trigger
                )
            except Exception as create_error:
                # Handle race condition where another request created it first
                # (unique index on wa_message_id for type=incoming, or IntegrityError)
                error_str = str(create_error)
                if (
                    'duplicate' in error_str.lower()
                    or 'unique constraint' in error_str.lower()
                    or 'unique index' in error_str.lower()
                    or getattr(create_error, 'pgcode', None) == '23505'  # unique_violation
                ):
                    # Transaction may be aborted (PostgreSQL); rollback so we can query
                    self.env.cr.rollback()
                    _logger.info(f"Chatbot message was created by another request for WhatsApp message {wa_message.id}, fetching existing record")
                    existing = self.sudo().search([
                        ('wa_message_id', '=', wa_message.id),
                        ('type', '=', 'incoming')
                    ], limit=1)
                    if existing:
                        return existing
                # Re-raise if it's a different error
                raise
            
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

