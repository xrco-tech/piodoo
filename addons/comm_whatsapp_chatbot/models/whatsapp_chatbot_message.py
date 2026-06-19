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
    
    # ── Channel adapters ─────────────────────────────────────────────────────

    def _send_message_via_channel(self, chatbot, step, recipient_phone, body,
                                  phone_number_id=None, context_message_id=None):
        """Route outbound sends through the chatbot's configured channel.
        Returns {'success': bool, 'message_id': str | None, 'error': str | None}."""
        if chatbot.channel == 'sms':
            return self._send_via_sms(recipient_phone, body)
        # Default: WhatsApp.
        return self._send_via_whatsapp(
            step=step,
            recipient_phone=recipient_phone,
            body=body,
            phone_number_id=phone_number_id,
            context_message_id=context_message_id,
        )

    def _send_via_whatsapp(self, step, recipient_phone, body,
                           phone_number_id=None, context_message_id=None):
        """Existing WhatsApp send path: interactive_flow uses the flow endpoint,
        everything else uses the plain message endpoint."""
        WhatsAppMessage = self.env['whatsapp.message'].sudo()
        wa_type = step.wa_message_type if step.step_type == 'question_interactive' else 'non_interactive'
        if wa_type == 'interactive_flow':
            return WhatsAppMessage.send_whatsapp_interactive_flow(
                recipient_phone=recipient_phone,
                step=step,
                phone_number_id=phone_number_id,
                context_message_id=context_message_id,
            )
        return WhatsAppMessage.send_whatsapp_message(
            recipient_phone=recipient_phone,
            message_text=body,
            phone_number_id=phone_number_id,
            context_message_id=context_message_id,
        )

    def _send_via_sms(self, recipient_phone, body):
        """Create and dispatch an sms.sms record. comm_sms picks the Infobip
        transport based on the sms.use_infobip_api config flag."""
        if not recipient_phone:
            return {'success': False, 'message_id': None, 'error': 'missing recipient'}
        try:
            sms = self.env['sms.sms'].sudo().create({
                'number': recipient_phone,
                'body': body or '',
            })
            sms._send(unlink_failed=False, unlink_sent=False, raise_exception=False)
            sms.flush_recordset()
            if sms.state in ('sent', 'pending', 'process'):
                return {'success': True, 'message_id': sms.uuid or str(sms.id), 'error': None}
            return {
                'success': False,
                'message_id': sms.uuid or str(sms.id),
                'error': sms.failure_type or sms.state or 'sms send failed',
            }
        except Exception as e:
            _logger.error(f"SMS send failed: {e}", exc_info=True)
            return {'success': False, 'message_id': None, 'error': str(e)}

    # ── USSD synchronous render walker ───────────────────────────────────────

    USSD_MAX_BODY_CHARS = 182  # carrier-imposed limit per screen

    @api.model
    def render_ussd_session(self, session, user_input):
        """Walk the flow for a USSD turn and return (body, terminate).

        body — the screen text (will be sent prefixed CON or END to the carrier)
        terminate — True if the session ends, False to keep it open

        On entry: session.current_step_id is the step that was waiting for the
        last user input (None on first turn). user_input is the most recent
        keypress / text (None on first turn).

        Note: variable + call_stack state lives on session.contact_id, NOT on
        the session record. A contact running parallel WA and USSD flows would
        therefore share state — accepted v1 limitation, document with caveats
        if it becomes a problem.
        """
        chatbot = session.chatbot_id
        if not chatbot:
            return ("Bot misconfigured.", True)
        try:
            entry_step = self._ussd_resolve_entry(session, user_input)
            if not entry_step:
                return ("This service has no flow configured.", True)
            body, terminate = self._ussd_walk(session, entry_step, user_input, depth=0)
            body = (body or '').strip()
            if len(body) > self.USSD_MAX_BODY_CHARS:
                body = body[:self.USSD_MAX_BODY_CHARS - 1] + '…'
            session.last_response = body
            if terminate:
                self._close_ussd_session(session, outcome='completed')
            return (body, terminate)
        except Exception as e:
            _logger.error(f"USSD render error in session {session.session_id}: {e}", exc_info=True)
            self._close_ussd_session(session, outcome='error')
            return ("Sorry, something went wrong.", True)

    def _ussd_resolve_entry(self, session, user_input):
        """Find which step to start this turn at.
        - First turn: root step of the chatbot.
        - Subsequent turns: the matched child of session.current_step_id based
          on user_input, or fall back to first child if no condition matches.
        """
        if not session.current_step_id:
            return self.env['whatsapp.chatbot.step'].sudo().search([
                ('chatbot_id', '=', session.chatbot_id.id),
                ('parent_id', '=', False),
            ], order='sequence asc, id asc', limit=1)
        current = session.current_step_id
        # Save the user's answer first (it'll be looked up by set_variable steps).
        if user_input is not None:
            self._ussd_record_answer(session, current, user_input)
        # Find matching child
        matched, _ = self._find_matching_child_step(current, user_input or '')
        if matched:
            return matched
        children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
        return children[0] if children else False

    def _ussd_record_answer(self, session, question_step, user_input):
        """Persist the user's input as an incoming chatbot message so the
        existing set_variable 'answer' source resolves correctly."""
        if not user_input:
            return
        self.sudo().create({
            'contact_id': session.contact_id.id,
            'mobile_number': session.phone_number or '',
            'chatbot_id': session.chatbot_id.id,
            'step_id': question_step.id,
            'message_plain': user_input,
            'message_html': user_input,
            'type': 'incoming',
        })

    def _ussd_walk(self, session, step, user_input, depth=0):
        """Accumulate body until we hit a step that waits for input (returns
        CON) or terminates the session (returns END). Reuses the same
        helpers (set_variable, jump_to_flow, end_flow) the push runtime uses."""
        if depth > MAX_RECURSION_DEPTH:
            return ("Flow too deep.", True)
        body_parts = []
        current = step
        guard = 0
        while current and guard < 50:
            guard += 1
            st = current.step_type
            if st == 'message':
                rendered = self._ussd_render_body(session, current.body_plain)
                if rendered:
                    body_parts.append(rendered)
                children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                if not children:
                    return (self._ussd_join(body_parts), True)
                if len(children) > 1:
                    body_parts.append(self._ussd_render_menu(children))
                    session.current_step_id = current.id
                    return (self._ussd_join(body_parts), False)
                current = children[0]
                continue
            if st.startswith('question_'):
                rendered = self._ussd_render_body(session, current.body_plain)
                if rendered:
                    body_parts.append(rendered)
                children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                if len(children) > 1:
                    body_parts.append(self._ussd_render_menu(children))
                session.current_step_id = current.id
                return (self._ussd_join(body_parts), False)
            if st == 'set_variable':
                # Reuse the push runtime's variable resolver — it works against
                # the contact's stored answer messages, which we just persisted.
                self._set_variable_from_step(self._ussd_message_facade(session), current)
                children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                current = children[0] if children else False
                continue
            if st == 'execute_code':
                try:
                    current.execute_code(self._ussd_message_facade(session))
                except Exception as e:
                    _logger.error(f"USSD execute_code failed on step {current.id}: {e}", exc_info=True)
                children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                current = children[0] if children else False
                continue
            if st == 'jump_to_flow':
                # Reuse existing jump infrastructure by mutating contact state.
                facade = self._ussd_message_facade(session)
                self._process_jump_to_flow_step(facade, current, depth=depth + 1)
                # The facade's step_id is now the entry step in the target bot.
                # Update session and continue from there.
                session.chatbot_id = facade.chatbot_id.id
                next_step = facade.step_id
                current = next_step
                continue
            if st == 'end_flow':
                # Pop call stack if any (mirrors _handle_end_flow's behavior)
                contact = session.contact_id
                stack = list(contact.call_stack or [])
                if stack:
                    frame = stack.pop()
                    contact.call_stack = stack
                    self._apply_var_mapping_snapshot(contact, frame.get('out_mapping') or [])
                    caller_bot = self.env['whatsapp.chatbot'].browse(frame.get('caller_chatbot_id')).exists()
                    jump_step = self.env['whatsapp.chatbot.step'].browse(frame.get('return_step_id')).exists()
                    if caller_bot and jump_step:
                        session.chatbot_id = caller_bot.id
                        children = jump_step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
                        current = children[0] if children else False
                        continue
                return (self._ussd_join(body_parts), True)
            if st == 'transfer_to_agent':
                # USSD has no live-handoff equivalent — render the body if any and end.
                rendered = self._ussd_render_body(session, current.body_plain)
                if rendered:
                    body_parts.append(rendered)
                return (self._ussd_join(body_parts), True)
            # Unknown step type — advance to first child or stop
            children = current.child_ids.sorted(key=lambda s: (s.sequence, s.id))
            current = children[0] if children else False
        return (self._ussd_join(body_parts), True)

    def _ussd_render_body(self, session, body_plain):
        if not body_plain:
            return ''
        variables = {v.variable_id.name: v for v in session.contact_id.variable_value_ids
                     if v.chatbot_id.id == session.chatbot_id.id}
        return self._replace_variables_in_message(body_plain, variables)

    def _ussd_render_menu(self, children):
        """Render a numbered menu from the trigger-answer values of children.
        Falls back to step names when no trigger answers are configured."""
        lines = []
        for i, child in enumerate(children, start=1):
            ans = child.trigger_answer_ids.sorted(key=lambda a: (a.sequence, a.id))
            label = ans[0].value if ans else child.name
            lines.append(f"{i}. {label}")
        return "\n".join(lines)

    def _ussd_join(self, body_parts):
        return "\n".join(p for p in body_parts if p)

    def _ussd_message_facade(self, session):
        """Return a transient chatbot_message-like record bound to the
        session's contact so the existing push-runtime helpers (set_variable,
        jump_to_flow) can mutate state without us reinventing them."""
        # Cache a single outgoing facade per session per turn.
        existing = self.search([
            ('contact_id', '=', session.contact_id.id),
            ('chatbot_id', '=', session.chatbot_id.id),
            ('type', '=', 'outgoing'),
        ], order='create_date desc', limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'contact_id': session.contact_id.id,
            'chatbot_id': session.chatbot_id.id,
            'mobile_number': session.phone_number or '',
            'message_plain': '',
            'message_html': '',
            'type': 'outgoing',
        })

    def _close_ussd_session(self, session, outcome='completed'):
        session.outcome = outcome

    # ── Channel routing helpers ─────────────────────────────────────────────

    def _find_chatbot_for_trigger(self, message_text, channel, sender_address=None):
        """Match a trigger word to a chatbot, preferring bots whose
        sender_address matches the inbound. Falls back to catch-all bots
        (sender_address blank) so pre-multi-number setups keep working."""
        if not message_text:
            return self.env['whatsapp.chatbot']
        Trigger = self.env['whatsapp.chatbot.trigger'].sudo()
        if sender_address:
            m = Trigger.search([
                ('name', '=ilike', message_text),
                ('chatbot_id.channel', '=', channel),
                ('chatbot_id.sender_address', '=', sender_address),
            ], limit=1)
            if m:
                return m.chatbot_id
        # Backward-compat: catch-all bots (sender_address blank)
        m = Trigger.search([
            ('name', '=ilike', message_text),
            ('chatbot_id.channel', '=', channel),
            '|',
            ('chatbot_id.sender_address', '=', False),
            ('chatbot_id.sender_address', '=', ''),
        ], limit=1)
        return m.chatbot_id if m else self.env['whatsapp.chatbot']

    def _is_engagement_valid(self, chatbot_contact, channel, sender_address=None):
        """Whether the contact's recorded engagement applies to this inbound.
        Engagement is scoped to (channel, sender_address) — a contact engaged
        in a bot on sender X doesn't continue when messaging on sender Y."""
        if not chatbot_contact.last_chatbot_id or not chatbot_contact.last_step_id:
            return False
        if chatbot_contact.last_step_id.step_type == 'end_flow':
            return False
        bot = chatbot_contact.last_chatbot_id
        if bot.channel != channel:
            return False
        bot_sender = bot.sender_address or ''
        if not bot_sender:
            # Catch-all bot — match any inbound on this channel (backward compat)
            return True
        if not sender_address:
            return False  # Bot expects a specific sender; we have none
        return bot_sender == sender_address

    def _mark_contact_entered(self, contact, chatbot):
        """Idempotently record that `contact` has entered `chatbot`.
        Tracked on the historical contact.chatbot_ids M2M (distinct from
        last_chatbot_id, which only reflects the currently engaged bot)."""
        if not contact or not chatbot:
            return
        # Avoid writing if the link already exists — saves a tracking message.
        if chatbot.id in contact.chatbot_ids.ids:
            return
        contact.sudo().write({'chatbot_ids': [(4, chatbot.id)]})

    def _resolve_trigger_for_engaged(self, current_chatbot, message_text,
                                     channel=None, sender_address=None):
        """Resolve trigger lookup for a contact already engaged in a flow.
        Returns (target_chatbot, kind) where kind is:
            'restart' — message matches a trigger on the current bot
            'switch'  — message matches a trigger on a DIFFERENT bot
            None      — no trigger match (treat message as a reply)

        When `channel` is given, cross-bot switches are restricted to bots on
        the same channel. When `sender_address` is also given, the cross-bot
        switch prefers bots with that sender, falling back to catch-all bots.
        Pure lookup — does NOT mutate any record.
        """
        if not message_text or not current_chatbot:
            return self.env['whatsapp.chatbot'], None
        Trigger = self.env['whatsapp.chatbot.trigger'].sudo()
        same = Trigger.search([
            ('name', '=ilike', message_text),
            ('chatbot_id', '=', current_chatbot.id),
        ], limit=1)
        if same:
            return current_chatbot, 'restart'
        if not channel:
            cross = Trigger.search([('name', '=ilike', message_text)], limit=1)
            if cross:
                return cross.chatbot_id, 'switch'
            return self.env['whatsapp.chatbot'], None
        # Channel-restricted lookup: prefer sender-specific bots.
        if sender_address:
            cross = Trigger.search([
                ('name', '=ilike', message_text),
                ('chatbot_id.channel', '=', channel),
                ('chatbot_id.sender_address', '=', sender_address),
            ], limit=1)
            if cross:
                return cross.chatbot_id, 'switch'
        cross = Trigger.search([
            ('name', '=ilike', message_text),
            ('chatbot_id.channel', '=', channel),
            '|',
            ('chatbot_id.sender_address', '=', False),
            ('chatbot_id.sender_address', '=', ''),
        ], limit=1)
        if cross:
            return cross.chatbot_id, 'switch'
        return self.env['whatsapp.chatbot'], None

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
        """Process a silent step (set_variable / execute_code), then auto-advance
        to the next step in the flow."""
        if depth > MAX_RECURSION_DEPTH:
            return message
        visited_steps = visited_steps or set()

        # Run side effects FIRST — set_variable's "answer" source looks up the
        # most recent incoming message with step_id = source_step_id, so we must
        # not have mutated message.step_id yet.
        if step.step_type == 'set_variable':
            self._set_variable_from_step(message, step)
        elif step.step_type == 'execute_code':
            try:
                step.execute_code(message)
            except Exception as e:
                _logger.error(f"execute_code failed on step {step.id}: {e}", exc_info=True)

        # Now track that the contact has moved through this step
        message.step_id = step.id
        message.contact_id.write({
            'last_chatbot_id': message.chatbot_id.id,
            'last_step_id': step.id,
            'last_seen_date': fields.Datetime.now(),
        })

        # Auto-advance: take the first child (silent chains assume single path)
        children = step.child_ids.sorted(key=lambda s: (s.sequence, s.id))
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

    def _set_variable_from_step(self, message, step):
        """Compute the source value per step.variable_data_source and upsert
        a whatsapp.chatbot.value row for (contact, target variable)."""
        if not step.variable_id:
            _logger.warning(f"set_variable step {step.id} has no target variable")
            return
        contact = message.contact_id
        target_var = step.variable_id
        value = False

        if step.variable_data_source == 'static':
            value = step.variable_value
        elif step.variable_data_source == 'answer':
            src_step = step.source_step_id
            if not src_step:
                _logger.warning(f"set_variable step {step.id} 'answer' source has no source_step_id")
                return
            # Find the most recent incoming reply to src_step (this will include
            # the current message when src_step is the question the user just answered)
            ans = self.env['whatsapp.chatbot.message'].sudo().search([
                ('contact_id', '=', contact.id),
                ('step_id', '=', src_step.id),
                ('type', '=', 'incoming'),
            ], order='create_date desc', limit=1)
            value = ans.message_plain if ans else False
        elif step.variable_data_source == 'variable':
            src_var = step.source_variable_id
            if not src_var:
                _logger.warning(f"set_variable step {step.id} 'variable' source has no source_variable_id")
                return
            src_val = self.env['whatsapp.chatbot.value'].sudo().search([
                ('contact_id', '=', contact.id),
                ('variable_id', '=', src_var.id),
            ], limit=1)
            value = src_val.value if src_val else False
        else:
            return

        Value = self.env['whatsapp.chatbot.value'].sudo()
        existing = Value.search([
            ('contact_id', '=', contact.id),
            ('variable_id', '=', target_var.id),
        ], limit=1)
        if existing:
            existing.value = value or False
        else:
            Value.create({
                'contact_id': contact.id,
                'variable_id': target_var.id,
                'value': value or False,
            })
        _logger.info(f"set_variable: {target_var.name} = {value!r} for contact {contact.id}")

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
        self._mark_contact_entered(contact, target_chatbot)

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
            
            # Send via the bot's configured channel adapter (WhatsApp or SMS).
            result = self._send_message_via_channel(
                chatbot=step.chatbot_id,
                step=step,
                recipient_phone=phone_number,
                body=processed_body,
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
            
            # Extract message text + recipient address for trigger matching
            message_text = message_body.strip() if message_body else ''
            phone_number_id = (value_data.get('metadata', {}) or {}).get('phone_number_id', '') or ''

            # Track whether we're starting from a trigger (send first step) or continuing (process reply)
            from_trigger = False
            chatbot = None
            if self._is_engagement_valid(chatbot_contact, 'whatsapp', phone_number_id):
                chatbot = chatbot_contact.last_chatbot_id
                _logger.info(f"Contact is actively engaged with chatbot: {chatbot.name}")

            # If not actively engaged, check for trigger words on a WhatsApp bot
            # whose sender_address matches the inbound's phone_number_id
            # (falling back to catch-all bots for backward compat).
            if not chatbot and message_text:
                resolved = self._find_chatbot_for_trigger(message_text, 'whatsapp', phone_number_id)
                if resolved:
                    from_trigger = True
                    chatbot = resolved
                    _logger.info(f"Trigger '{message_text}' matched to chatbot: {chatbot.name}")
                    # Clear all variables when starting a new chatbot flow
                    chatbot_contact.variable_value_ids.unlink()
                    # Reset last step and call stack
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                        'call_stack': [],
                    })
                    self._mark_contact_entered(chatbot_contact, chatbot)
                else:
                    # No trigger matched - don't assign a chatbot
                    # Only process messages that match triggers or are already in a conversation
                    _logger.info(f"No trigger matched for message '{message_text}'. Skipping chatbot processing.")
                    return
            
            # Only continue if we have a chatbot (either from active conversation or trigger match)
            if not chatbot:
                _logger.warning("No chatbot found to process message")
                return
            
            # If user is engaged but sends a trigger word, restart (same-bot
            # trigger wins) or switch to another bot (cross-bot trigger).
            if chatbot and message_text and not from_trigger:
                target, kind = self._resolve_trigger_for_engaged(
                    chatbot, message_text,
                    channel='whatsapp', sender_address=phone_number_id,
                )
                if target:
                    from_trigger = True
                    if kind == 'switch':
                        _logger.info(
                            f"Trigger '{message_text}' while engaged with '{chatbot.name}': "
                            f"switching to chatbot '{target.name}'"
                        )
                        chatbot = target
                    else:
                        _logger.info(f"Trigger '{message_text}' while engaged: restarting flow for {chatbot.name}")
                    chatbot_contact.variable_value_ids.unlink()
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                        'call_stack': [],
                    })
                    self._mark_contact_entered(chatbot_contact, chatbot)
            
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
    
    @api.model
    def process_incoming_sms_message(self, from_number, message_text,
                                     sms_message_id=None, to_number=None):
        """Process an inbound SMS through the chatbot system. Called by the
        Infobip MO webhook controller after normalising the payload.

        Mirrors process_incoming_webhook_message but routes all trigger and
        engagement lookups through the SMS channel. `to_number` is the SMS
        sender ID the user sent to — used to route to the right bot when
        multiple SMS bots share the same Odoo install.
        """
        try:
            ChatbotContact = self.env['whatsapp.chatbot.contact'].sudo()
            from_number = (from_number or '').strip()
            message_text = (message_text or '').strip()
            to_number = (to_number or '').strip()
            if not from_number:
                _logger.warning("Inbound SMS missing sender number")
                return

            partner = self._find_or_create_partner(
                from_number, {'wa_id': from_number, 'profile': {}},
            )
            if not partner:
                _logger.warning(f"Could not find or create partner for SMS from {from_number}")
                return

            chatbot_contact = ChatbotContact.search([('partner_id', '=', partner.id)], limit=1)
            if not chatbot_contact:
                chatbot_contact = ChatbotContact.create({'partner_id': partner.id})

            from_trigger = False
            chatbot = None

            # Engagement only carries over within (channel, sender_address).
            if self._is_engagement_valid(chatbot_contact, 'sms', to_number):
                chatbot = chatbot_contact.last_chatbot_id
                _logger.info(f"SMS contact actively engaged with chatbot: {chatbot.name}")

            if not chatbot and message_text:
                resolved = self._find_chatbot_for_trigger(message_text, 'sms', to_number)
                if resolved:
                    from_trigger = True
                    chatbot = resolved
                    _logger.info(f"SMS trigger '{message_text}' matched chatbot: {chatbot.name}")
                    chatbot_contact.variable_value_ids.unlink()
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                        'call_stack': [],
                    })
                    self._mark_contact_entered(chatbot_contact, chatbot)
                else:
                    _logger.info(f"No SMS trigger matched '{message_text}'. Skipping.")
                    return

            if not chatbot:
                _logger.warning("No SMS chatbot found to process message")
                return

            # Engaged + matched a trigger word → restart or switch within SMS channel.
            if chatbot and message_text and not from_trigger:
                target, kind = self._resolve_trigger_for_engaged(
                    chatbot, message_text,
                    channel='sms', sender_address=to_number,
                )
                if target:
                    from_trigger = True
                    if kind == 'switch':
                        _logger.info(
                            f"SMS trigger '{message_text}' while engaged with '{chatbot.name}': "
                            f"switching to chatbot '{target.name}'"
                        )
                        chatbot = target
                    else:
                        _logger.info(f"SMS trigger '{message_text}' while engaged: restarting flow for {chatbot.name}")
                    chatbot_contact.variable_value_ids.unlink()
                    chatbot_contact.write({
                        'last_chatbot_id': chatbot.id,
                        'last_step_id': False,
                        'call_stack': [],
                    })
                    self._mark_contact_entered(chatbot_contact, chatbot)

            if from_trigger:
                step_to_use = self.env['whatsapp.chatbot.step'].sudo().search([
                    ('chatbot_id', '=', chatbot.id),
                    ('parent_id', '=', False),
                ], order='sequence asc', limit=1)
            else:
                step_to_use = chatbot_contact.last_step_id

            chatbot_message = self.create({
                'contact_id': chatbot_contact.id,
                'mobile_number': from_number,
                'chatbot_id': chatbot.id,
                'message_plain': message_text,
                'message_html': message_text,
                'type': 'incoming',
                'step_id': step_to_use.id if step_to_use else False,
            })
            _logger.info(
                f"Created incoming SMS chatbot message: {chatbot_message.id} "
                f"(infobip messageId={sms_message_id})"
            )
            chatbot_message.flush_recordset()

            return self._handle_incoming_message(
                chatbot_message, depth=0, visited_steps=set(), from_trigger=from_trigger,
            )
        except Exception as e:
            _logger.error(f"Error processing SMS chatbot message: {e}", exc_info=True)

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

