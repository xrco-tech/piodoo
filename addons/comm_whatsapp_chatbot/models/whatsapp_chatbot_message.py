# -*- coding: utf-8 -*-

import logging
import re
from odoo import api, models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup

_logger = logging.getLogger(__name__)

MAX_RECURSION_DEPTH = 10
MAX_CALL_STACK_DEPTH = 8  # subroutine nesting limit (jump_to_flow)


class WhatsAppChatbotMessage(models.Model):
    _name = 'whatsapp.chatbot.message'
    _description = 'WhatsApp Chatbot Message'
    _order = 'create_date desc'

    contact_id = fields.Many2one("whatsapp.chatbot.contact", string="Contact", required=True, tracking=True, ondelete='cascade')
    mobile_number = fields.Char(string="WhatsApp Number", tracking=True)
    step_id = fields.Many2one("whatsapp.chatbot.step", string="Chatbot Step", tracking=True)
    # Make chatbot_id a regular Many2one instead of a related field so it's always available
    chatbot_id = fields.Many2one("whatsapp.chatbot", string="Chatbot", required=True, tracking=True)
    
    # Link to comm_whatsapp message
    wa_message_id = fields.Many2one("whatsapp.message", string="Related WhatsApp Message", tracking=True)
    
    message_plain = fields.Char(string="Plain Message", tracking=True)
    message_html = fields.Html(string="HTML Message", tracking=True)
    message_formatted_html = fields.Html(string="Formatted HTML Message", compute='_compute_message_formatted_html', sanitize=False, store=False)
    message_preview_html = fields.Html(string='Message Preview', compute='_compute_message_preview_html', sanitize=False)
    
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
    
    @api.depends('message_html', 'message_plain')
    def _compute_message_formatted_html(self):
        """Compute formatted HTML version of message for display in form view"""
        for record in self:
            if record.message_html:
                # Check if message_html is already HTML (contains tags) or plain text
                html_content = str(record.message_html)
                if '<' in html_content and '>' in html_content:
                    # Already HTML, use as-is
                    record.message_formatted_html = Markup(html_content)
                else:
                    # Plain text in HTML field, format it
                    record.message_formatted_html = self._format_whatsapp_text(html_content)
            elif record.message_plain:
                # Format plain text
                record.message_formatted_html = self._format_whatsapp_text(record.message_plain)
            else:
                record.message_formatted_html = False
    
    @api.depends('message_html', 'message_plain', 'type', 'create_date')
    def _compute_message_preview_html(self):
        """Compute HTML preview of the message using QWeb template"""
        for record in self:
            try:
                # Choose template based on message direction
                template_name = 'comm_whatsapp_chatbot.chatbot_message_preview_received' if record.type == 'incoming' else 'comm_whatsapp_chatbot.chatbot_message_preview'
                
                # Get message content - prefer plain text for formatting, fallback to HTML
                # If message_html exists and contains HTML tags, use it directly; otherwise format plain text
                message_body = ''
                message_plain = record.message_plain or ''
                
                if record.message_html:
                    # Check if message_html is already HTML (contains tags) or plain text
                    html_content = str(record.message_html)
                    if '<' in html_content and '>' in html_content:
                        # Already HTML, use as-is
                        message_body = Markup(html_content)
                    else:
                        # Plain text in HTML field, format it
                        message_body = self._format_whatsapp_text(html_content)
                elif message_plain:
                    # Format plain text
                    message_body = self._format_whatsapp_text(message_plain)
                
                # Format timestamp for display
                timestamp_str = ''
                if record.create_date:
                    try:
                        # Format as HH:MM
                        timestamp_str = record.create_date.strftime('%H:%M')
                    except (AttributeError, ValueError):
                        # Fallback if create_date is not a datetime
                        timestamp_str = str(record.create_date) if record.create_date else ''
                
                # Render preview using QWeb template
                preview = self.env['ir.ui.view']._render_template(template_name, {
                    'message_body': message_body,
                    'message_plain': message_plain,
                    'timestamp': timestamp_str,
                    'create_date': record.create_date,  # Keep for backward compatibility
                    'type': record.type,
                })
                
                record.message_preview_html = preview.decode('utf-8') if isinstance(preview, bytes) else preview
            except Exception as e:
                _logger.error(f"Error rendering chatbot message preview: {e}", exc_info=True)
                record.message_preview_html = f'<div style="color: red;">Error rendering preview: {str(e)}</div>'
    
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
            if message.step_id.step_type == 'jump_to_flow':
                return self._process_jump_to_flow_step(message, message.step_id, depth=depth + 1, visited_steps=visited_steps)
            if message.step_id.step_type == 'end_flow':
                return self._handle_end_flow(message, message.step_id, depth=depth + 1, visited_steps=visited_steps)
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
                if first_step.step_type == 'jump_to_flow':
                    return self._process_jump_to_flow_step(message, first_step, depth=depth + 1, visited_steps=visited_steps)
                if first_step.step_type == 'end_flow':
                    return self._handle_end_flow(message, first_step, depth=depth + 1, visited_steps=visited_steps)
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

    def _evaluate_answer_condition(self, answer_record, user_answer):
        """
        Evaluate if a user's answer matches an answer condition.
        Returns True if the condition matches, False otherwise.
        """
        if not answer_record or not user_answer:
            return False
        
        operator = answer_record.operator
        expected_value = answer_record.value or ''
        user_value = str(user_answer).strip()
        
        # Normalize for comparison (case-insensitive for text)
        if answer_record.answer_data_type == 'text':
            expected_value = expected_value.upper().strip()
            user_value = user_value.upper().strip()
        
        if operator == 'is_equal_to':
            return user_value == expected_value
        elif operator == 'is_not_equal_to':
            return user_value != expected_value
        elif operator == 'contains':
            # Check if user's answer contains the expected value
            return expected_value in user_value
        elif operator == 'does_not_contain':
            # Check if user's answer does NOT contain the expected value
            return expected_value not in user_value
        elif operator == 'less_than':
            try:
                return float(user_value) < float(expected_value)
            except (ValueError, TypeError):
                return False
        elif operator == 'greater_than':
            try:
                return float(user_value) > float(expected_value)
            except (ValueError, TypeError):
                return False
        return False
    
    def _find_matching_child_step(self, current_step, user_answer, message=None):
        """
        Find the child step that matches the user's answer based on trigger_answer_ids.
        Returns tuple (matching_step, matched_answer_record) or (None, None) if no match found.
        """
        if not current_step or not user_answer:
            return None, None
        
        children = current_step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
        
        # First, try to find a step with matching trigger_answer_ids
        # Check steps in sequence order to ensure consistent matching
        for child_step in children:
            if child_step.trigger_answer_ids:
                _logger.debug(f"Checking step '{child_step.name}' (ID: {child_step.id}) with {len(child_step.trigger_answer_ids)} trigger answers")
                # Check if any trigger answer matches the user's answer
                # Sort answers by sequence to check in order
                sorted_answers = child_step.trigger_answer_ids.sorted(key=lambda a: (a.sequence, a.id))
                for answer_record in sorted_answers:
                    matches = self._evaluate_answer_condition(answer_record, user_answer)
                    _logger.debug(f"  Checking answer '{answer_record.value}' (operator: {answer_record.operator}): {matches}")
                    if matches:
                        _logger.info(f"Answer '{user_answer}' matched condition '{answer_record.display_name}' for step '{child_step.name}' (ID: {child_step.id})")
                        # Store the matched answer in the message if provided
                        if message:
                            message.user_chatbot_answer_id = answer_record.id
                        return child_step, answer_record
        
        # If no step has trigger_answer_ids or no match found, return None
        # (caller will fall back to first child)
        return None, None
    
    def _process_chatbot_flow(self, message, depth=0, visited_steps=None):
        """
        Process user reply: match user's answer to child steps based on trigger_answer_ids,
        or fall back to first child by sequence if no match.
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
        
        # Get user's answer from the incoming message
        user_answer = message.message_plain or ''
        if not user_answer and message.message_html:
            from markupsafe import Markup
            user_answer = Markup(message.message_html).striptags()
        user_answer = user_answer.strip() if user_answer else ''
        
        _logger.info(f"Processing reply to step '{current_step.name}': user answered '{user_answer}'")
        
        # Get all child steps sorted by sequence
        children = current_step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
        if not children:
            self._update_contact_last_interaction(message)
            return message
        
        # Try to find a matching child step based on trigger_answer_ids
        next_step, matched_answer = self._find_matching_child_step(current_step, user_answer, message)
        
        # If no match found, fall back to first child (backward compatibility)
        if not next_step:
            next_step = children[0]
            _logger.info(f"No matching answer condition found for '{user_answer}', using first child step: {next_step.name}")
        else:
            _logger.info(f"Matched answer '{user_answer}' to step '{next_step.name}' via condition '{matched_answer.display_name if matched_answer else 'N/A'}'")
        
        if next_step.step_type == 'end_flow':
            return self._handle_end_flow(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        if next_step.step_type in ['set_variable', 'execute_code']:
            return self._process_variable_or_code_step(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        if next_step.step_type == 'jump_to_flow':
            return self._process_jump_to_flow_step(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        _logger.info(f"Advancing from step '{current_step.name}' to '{next_step.name}' (ID: {next_step.id})")
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

    # ── Jump to Flow/Bot ────────────────────────────────────────────────────────

    def _process_jump_to_flow_step(self, message, jump_step, depth=0, visited_steps=None):
        """Dispatch a jump_to_flow step: switch active chatbot, apply variable
        mappings, push a stack frame in subroutine mode, and continue at the
        entry step of the target chatbot."""
        if depth > MAX_RECURSION_DEPTH:
            _logger.warning("Max recursion depth in _process_jump_to_flow_step")
            return message
        visited_steps = visited_steps or set()

        contact = message.contact_id
        target_chatbot = jump_step.target_chatbot_id
        if not target_chatbot:
            _logger.error(f"Jump step {jump_step.id} ({jump_step.name}) has no target chatbot")
            return message

        stack = list(contact.call_stack or [])
        if len(stack) >= MAX_CALL_STACK_DEPTH:
            _logger.warning(
                f"Call stack depth {len(stack)} reached MAX_CALL_STACK_DEPTH; "
                f"refusing jump from step {jump_step.id}"
            )
            return message

        # Resolve entry step (explicit target_step_id or target chatbot's root step)
        entry = jump_step.target_step_id
        if not entry:
            entry = self.env['whatsapp.chatbot.step'].search([
                ('chatbot_id', '=', target_chatbot.id),
                ('parent_id', '=', False),
            ], order='sequence asc, id asc', limit=1)
        if not entry:
            _logger.error(f"No entry step for target chatbot {target_chatbot.id}")
            return message

        # In/both mapping: caller variables → callee variables
        self._apply_var_mapping(
            contact, jump_step.variable_mapping_ids,
            directions=('in', 'both'), reverse=False,
        )

        # Push subroutine frame (snapshot out-mapping so mid-session edits are safe)
        if jump_step.jump_mode == 'subroutine':
            out_rows = [
                {'src_var': m.source_variable_id.id, 'tgt_var': m.target_variable_id.id}
                for m in jump_step.variable_mapping_ids
                if m.direction in ('out', 'both')
            ]
            stack.append({
                'caller_chatbot_id': jump_step.chatbot_id.id,
                'return_step_id': jump_step.id,
                'out_mapping': out_rows,
            })
            contact.call_stack = stack

        # Switch active chatbot/step on both message and contact
        message.chatbot_id = target_chatbot.id
        message.step_id = entry.id
        contact.write({
            'last_chatbot_id': target_chatbot.id,
            'last_step_id': entry.id,
            'last_seen_date': fields.Datetime.now(),
        })

        _logger.info(
            f"Jumped to chatbot '{target_chatbot.name}' entry step '{entry.name}' "
            f"(mode={jump_step.jump_mode}, stack_depth={len(stack)})"
        )

        # Dispatch the entry step
        if entry.step_type == 'jump_to_flow':
            return self._process_jump_to_flow_step(message, entry, depth=depth + 1, visited_steps=visited_steps)
        if entry.step_type in ('set_variable', 'execute_code'):
            return self._process_variable_or_code_step(message, entry, depth=depth + 1, visited_steps=visited_steps)
        if entry.step_type == 'end_flow':
            return self._handle_end_flow(message, entry, depth=depth + 1, visited_steps=visited_steps)
        return self._send_step_message(message, entry)

    def _handle_end_flow(self, message, end_step, depth=0, visited_steps=None):
        """Handle reaching an end_flow step. If the contact has subroutine frames,
        pop the top frame, copy out-mapped variables back to the caller, and
        resume from the jump step's first child. Otherwise terminate."""
        if depth > MAX_RECURSION_DEPTH:
            return message
        visited_steps = visited_steps or set()
        contact = message.contact_id
        stack = list(contact.call_stack or [])

        if not stack:
            contact.write({
                'last_chatbot_id': message.chatbot_id.id,
                'last_step_id': end_step.id,
                'last_seen_date': fields.Datetime.now(),
            })
            return message

        frame = stack.pop()
        contact.call_stack = stack

        # Out mapping snapshot: callee variables → caller variables
        self._apply_var_mapping_snapshot(contact, frame.get('out_mapping') or [])

        caller_chatbot_id = frame.get('caller_chatbot_id')
        return_step_id = frame.get('return_step_id')
        caller_chatbot = self.env['whatsapp.chatbot'].browse(caller_chatbot_id).exists() if caller_chatbot_id else False
        jump_step = self.env['whatsapp.chatbot.step'].browse(return_step_id).exists() if return_step_id else False

        if not caller_chatbot or not jump_step:
            _logger.warning("Subroutine return frame missing caller context; terminating")
            return message

        message.chatbot_id = caller_chatbot.id
        message.step_id = jump_step.id
        contact.write({
            'last_chatbot_id': caller_chatbot.id,
            'last_step_id': jump_step.id,
            'last_seen_date': fields.Datetime.now(),
        })
        _logger.info(
            f"Returned from subroutine to chatbot '{caller_chatbot.name}' "
            f"at jump step '{jump_step.name}' (stack_depth={len(stack)})"
        )

        # Resume from jump step's first non-end child (if any)
        children = jump_step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
        if not children:
            return message
        next_step = children[0]
        if next_step.step_type == 'end_flow':
            return self._handle_end_flow(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        if next_step.step_type == 'jump_to_flow':
            return self._process_jump_to_flow_step(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        if next_step.step_type in ('set_variable', 'execute_code'):
            return self._process_variable_or_code_step(message, next_step, depth=depth + 1, visited_steps=visited_steps)
        return self._send_step_message(message, next_step)

    def _apply_var_mapping(self, contact, mapping_records, directions, reverse=False):
        """Copy variable values per mapping rows.
        reverse=False: source_variable_id (caller) → target_variable_id (callee)
        reverse=True:  target_variable_id (callee) → source_variable_id (caller)
        Filters rows by direction tuple.
        """
        Value = self.env['whatsapp.chatbot.value'].sudo()
        for m in mapping_records:
            if m.direction not in directions:
                continue
            src = m.target_variable_id if reverse else m.source_variable_id
            tgt = m.source_variable_id if reverse else m.target_variable_id
            if not src or not tgt:
                continue
            src_val = Value.search([
                ('contact_id', '=', contact.id),
                ('variable_id', '=', src.id),
            ], limit=1)
            v = src_val.value if src_val else False
            existing = Value.search([
                ('contact_id', '=', contact.id),
                ('variable_id', '=', tgt.id),
            ], limit=1)
            if existing:
                existing.value = v
            else:
                Value.create({
                    'contact_id': contact.id,
                    'variable_id': tgt.id,
                    'value': v,
                })

    def _apply_var_mapping_snapshot(self, contact, out_rows):
        """Apply an out-mapping snapshot stored on a stack frame.
        Each row: {'src_var': caller_var_id, 'tgt_var': callee_var_id}.
        Copies callee_var (tgt) → caller_var (src) at return time.
        """
        Value = self.env['whatsapp.chatbot.value'].sudo()
        Variable = self.env['whatsapp.chatbot.variable'].sudo()
        for row in out_rows or []:
            src_var = Variable.browse(row.get('src_var')).exists()
            tgt_var = Variable.browse(row.get('tgt_var')).exists()
            if not src_var or not tgt_var:
                continue
            callee_val = Value.search([
                ('contact_id', '=', contact.id),
                ('variable_id', '=', tgt_var.id),
            ], limit=1)
            v = callee_val.value if callee_val else False
            caller_existing = Value.search([
                ('contact_id', '=', contact.id),
                ('variable_id', '=', src_var.id),
            ], limit=1)
            if caller_existing:
                caller_existing.value = v
            else:
                Value.create({
                    'contact_id': contact.id,
                    'variable_id': src_var.id,
                    'value': v,
                })

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
            
            # Send message via WhatsApp API — branch on step message type
            WhatsAppMessage = self.env['whatsapp.message'].sudo()
            wa_type = step.wa_message_type if step.step_type == 'question_interactive' else 'non_interactive'

            if wa_type == 'interactive_flow':
                result = WhatsAppMessage.send_whatsapp_interactive_flow(
                    recipient_phone=phone_number,
                    step=step,
                    phone_number_id=phone_number_id,
                    context_message_id=context_message_id,
                )
            else:
                result = WhatsAppMessage.send_whatsapp_message(
                    recipient_phone=phone_number,
                    message_text=processed_body,
                    phone_number_id=phone_number_id,
                    context_message_id=context_message_id,
                )
            
            if result.get('success'):
                _logger.info(f"Chatbot message sent successfully: {result.get('message_id')}")
                
                # Create outgoing chatbot message record
                # Note: Incoming message was already flushed to DB before this flow started
                outgoing_message = self.create({
                    'contact_id': message.contact_id.id,
                    'mobile_number': phone_number,
                    'step_id': step.id,
                    'chatbot_id': step.chatbot_id.id,
                    'message_html': processed_body,
                    'message_plain': processed_body,
                    'type': 'outgoing',
                })
                _logger.info(f"Created outgoing chatbot message: {outgoing_message.id} (incoming message {message.id} was saved first)")
                
                # Flush outgoing message to ensure proper ordering
                self.env.cr.flush()
                
                # Update contact's last step
                self._update_contact_last_interaction(outgoing_message)
                
                # Auto-advance: only for non-question steps (message, set_variable, etc.)
                # Question/interactive steps wait for user input — never auto-advance them.
                WAIT_FOR_INPUT = {'question_text', 'question_interactive'}
                children = step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                if step.step_type not in WAIT_FOR_INPUT and len(children) == 1:
                    child = children[0]
                    if child.step_type == 'jump_to_flow':
                        _logger.info(f"Auto-advancing to jump step: {child.name} (ID: {child.id})")
                        return self._process_jump_to_flow_step(message, child)
                    if child.step_type == 'end_flow':
                        # Pop subroutine frame if any, otherwise stay (preserves prior behavior).
                        if message.contact_id.call_stack:
                            _logger.info(f"Auto-advancing to end_flow with active call stack: pop")
                            return self._handle_end_flow(message, child)
                    elif child.step_type != 'end_flow':
                        _logger.info(f"Auto-advancing to next step: {child.name} (ID: {child.id})")
                        return self._send_step_message(message, child)
                
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
                    # Reset last step and call stack
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                        'call_stack': [],
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
                        'call_stack': [],
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
                _logger.info(f"Created incoming chatbot message: {chatbot_message.id}")
                
                # CRITICAL: Flush the incoming message to database before processing flow
                # This ensures the incoming message is saved before any outgoing replies are created
                chatbot_message.flush_recordset()
                _logger.info(f"Incoming message {chatbot_message.id} flushed to database before processing flow")
                
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

