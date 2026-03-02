# -*- coding: utf-8 -*-
"""
Omni-channel chatbot for Contact Centre.

This model acts as a thin configuration wrapper around `whatsapp.chatbot`
(from whatsapp_custom) and extends it to support SMS and email channels.

Architecture
------------
- `contact.centre.chatbot`  – configures WHICH whatsapp.chatbot flow to use on
  each channel, defines keyword triggers and the fallback welcome message.
- `contact.centre.chatbot.session` – tracks per-contact conversation state
  (current step, collected variables, channel, active-agent mode).

Inbound message routing (webhook_controller.py) calls
`contact.centre.chatbot._route_inbound(contact, channel, body)` which:
  1. Finds the matching chatbot by keyword trigger (or default).
  2. Retrieves or creates the session for the contact/channel pair.
  3. Delegates step-execution to `whatsapp.chatbot.message` on WhatsApp, or
     to the inline SMS/email step runner for other channels.
"""

import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ContactCentreChatbot(models.Model):
    _name = 'contact.centre.chatbot'
    _description = 'Contact Centre Chatbot'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence asc, id asc'

    # -------------------------------------------------------------------------
    # Identity & Config
    # -------------------------------------------------------------------------

    name = fields.Char('Chatbot Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    sequence = fields.Integer('Priority', default=10,
                              help='Lower value = higher priority when matching triggers')
    description = fields.Text('Description')

    # Channels on which this chatbot is active
    channel_whatsapp = fields.Boolean('WhatsApp', default=True)
    channel_sms = fields.Boolean('SMS', default=False)
    channel_email = fields.Boolean('Email', default=False)

    # Delegate the actual flow to the whatsapp.chatbot engine
    wa_chatbot_id = fields.Many2one(
        'whatsapp.chatbot',
        'Flow (WhatsApp Chatbot)',
        required=True,
        ondelete='restrict',
        help='The WhatsApp chatbot whose step-flow this chatbot will execute',
    )

    # Trigger keywords that activate this chatbot (comma-separated or one per line)
    trigger_keywords = fields.Text(
        'Trigger Keywords',
        help='One keyword per line. An inbound message matching any of these '
             '(case-insensitive) will start this chatbot. Leave blank to use '
             'as the default/fallback chatbot.',
    )
    is_default = fields.Boolean(
        'Default Chatbot',
        default=False,
        help='Use this chatbot when no keyword trigger matches. '
             'Only one chatbot should be set as default per channel.',
        tracking=True,
    )
    welcome_message = fields.Text(
        'Welcome / Restart Message',
        help='Sent when the chatbot is triggered. Leave blank to go straight '
             'to the first step.',
    )
    end_message = fields.Text(
        'End Message',
        help='Sent when the flow ends (end_flow step or no more steps).',
    )

    # Campaign linkage (optional)
    campaign_id = fields.Many2one('contact.centre.campaign', 'Campaign',
                                  ondelete='set null', index=True)

    # -------------------------------------------------------------------------
    # Stat buttons
    # -------------------------------------------------------------------------

    session_ids = fields.One2many('contact.centre.chatbot.session', 'chatbot_id', 'Sessions')
    session_count = fields.Integer('Sessions', compute='_compute_session_count')

    @api.depends('session_ids')
    def _compute_session_count(self):
        for bot in self:
            bot.session_count = len(bot.session_ids)

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sessions',
            'res_model': 'contact.centre.chatbot.session',
            'view_mode': 'list,form',
            'domain': [('chatbot_id', '=', self.id)],
        }

    # -------------------------------------------------------------------------
    # Keyword matching helpers
    # -------------------------------------------------------------------------

    def _get_trigger_keywords(self):
        """Return a list of normalised keywords for this chatbot."""
        self.ensure_one()
        if not self.trigger_keywords:
            return []
        return [
            kw.strip().lower()
            for kw in re.split(r'[\n,;]+', self.trigger_keywords)
            if kw.strip()
        ]

    @api.model
    def _find_matching_chatbot(self, channel_field, message_body):
        """
        Return the best matching active chatbot for a given channel and message.

        Priority:
        1. Exact keyword match (lowest sequence wins).
        2. Default chatbot for the channel (lowest sequence wins).
        3. None – caller handles the no-bot case.
        """
        domain = [(channel_field, '=', True), ('active', '=', True)]
        bots = self.search(domain, order='sequence asc')

        body_lower = (message_body or '').strip().lower()
        for bot in bots:
            for kw in bot._get_trigger_keywords():
                if kw and kw in body_lower:
                    return bot

        for bot in bots:
            if bot.is_default:
                return bot

        return None

    # -------------------------------------------------------------------------
    # Main entry point called by the webhook controller
    # -------------------------------------------------------------------------

    @api.model
    def route_inbound(self, contact, channel, body, cc_message=None):
        """
        Route an inbound message to the appropriate chatbot (if any).

        :param contact: contact.centre.contact record
        :param channel: 'whatsapp' | 'sms' | 'email'
        :param body: plain-text message body
        :param cc_message: contact.centre.message record (optional, for linking)
        :returns: True if a chatbot handled the message, False otherwise
        """
        channel_field_map = {
            'whatsapp': 'channel_whatsapp',
            'sms': 'channel_sms',
            'email': 'channel_email',
        }
        channel_field = channel_field_map.get(channel)
        if not channel_field:
            return False

        # Find or continue an active session for this contact+channel
        session = self.env['contact.centre.chatbot.session'].search([
            ('contact_id', '=', contact.id),
            ('channel', '=', channel),
            ('state', '=', 'active'),
        ], limit=1)

        if session:
            chatbot = session.chatbot_id
        else:
            chatbot = self._find_matching_chatbot(channel_field, body)
            if not chatbot:
                return False
            session = self.env['contact.centre.chatbot.session'].create({
                'chatbot_id': chatbot.id,
                'contact_id': contact.id,
                'channel': channel,
                'state': 'active',
            })
            # Send welcome message if configured
            if chatbot.welcome_message:
                self._send_reply(contact, channel, chatbot.welcome_message)

        # Delegate step processing to the whatsapp.chatbot message engine
        # (works for WhatsApp; SMS/email use a simplified text runner)
        if channel == 'whatsapp':
            session._process_step_whatsapp(body, cc_message)
        else:
            session._process_step_text(body)

        return True

    def _send_reply(self, contact, channel, text):
        """Send a text reply via the appropriate channel."""
        if channel == 'whatsapp':
            self._send_whatsapp_reply(contact, text)
        elif channel == 'sms':
            self._send_sms_reply(contact, text)

    def _send_whatsapp_reply(self, contact, text):
        phone = contact.phone_number
        if not phone:
            return
        wa_account = (
            self.wa_chatbot_id.wa_account_id
            or self.env['whatsapp.account'].search([], limit=1)
        )
        if not wa_account:
            _logger.warning("No WhatsApp account configured for chatbot reply")
            return
        try:
            self.env['whatsapp.message'].sudo().create({
                'mobile_number': phone,
                'wa_account_id': wa_account.id,
                'message_type': 'outbound',
                'body': text,
                'state': 'outgoing',
            })
        except Exception as e:
            _logger.error("Failed to send WhatsApp chatbot reply: %s", e)

    def _send_sms_reply(self, contact, text):
        phone = contact.phone_number
        if not phone:
            return
        try:
            self.env['sms.sms'].sudo().create({
                'number': phone,
                'body': text,
                'state': 'outgoing',
            })._send()
        except Exception as e:
            _logger.error("Failed to send SMS chatbot reply: %s", e)


class ContactCentreChatbotSession(models.Model):
    _name = 'contact.centre.chatbot.session'
    _description = 'Contact Centre Chatbot Session'
    _order = 'write_date desc, id desc'

    chatbot_id = fields.Many2one('contact.centre.chatbot', 'Chatbot',
                                 required=True, ondelete='cascade', index=True)
    contact_id = fields.Many2one('contact.centre.contact', 'Contact',
                                 required=True, ondelete='cascade', index=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ], 'Channel', required=True, index=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('waiting_human', 'Waiting for Human Agent'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ], 'State', default='active', index=True)

    # Current position in the flow
    current_step_id = fields.Many2one(
        'whatsapp.chatbot.step',
        'Current Step',
        ondelete='set null',
    )
    # Link to the whatsapp.chatbot.contact that the WA engine manages
    wa_chatbot_contact_id = fields.Many2one(
        'whatsapp.chatbot.contact',
        'WA Chatbot Contact',
        ondelete='set null',
    )

    # Collected data (JSON store for non-WA channels)
    collected_data = fields.Json('Collected Data', default=dict)

    message_count = fields.Integer('Messages', compute='_compute_message_count')
    message_ids = fields.One2many(
        'contact.centre.chatbot.session.message',
        'session_id',
        'Messages',
    )

    @api.depends('message_ids')
    def _compute_message_count(self):
        for s in self:
            s.message_count = len(s.message_ids)

    def action_end_session(self):
        self.write({'state': 'completed'})

    def action_escalate_to_human(self):
        self.write({'state': 'waiting_human'})

    # -------------------------------------------------------------------------
    # Step processing – WhatsApp (delegated to whatsapp.chatbot.message engine)
    # -------------------------------------------------------------------------

    def _process_step_whatsapp(self, body, cc_message=None):
        """
        Process one inbound WhatsApp message through the WA chatbot engine.

        The whatsapp.chatbot.message model owns the full step-routing logic
        (answer-matching, variable setting, code execution, etc.).  We look
        up (or create) the whatsapp.chatbot.contact for this contact's phone
        number so the WA engine can operate on it normally.
        """
        self.ensure_one()
        WaChatbotContact = self.env['whatsapp.chatbot.contact'].sudo()
        phone = self.contact_id.phone_number

        wa_contact = self.wa_chatbot_contact_id
        if not wa_contact:
            wa_contact = WaChatbotContact.search(
                [('mobile_number', '=', phone),
                 ('last_chatbot_id', '=', self.chatbot_id.wa_chatbot_id.id)],
                limit=1
            )
            if not wa_contact:
                partner = self.contact_id.partner_id
                wa_contact = WaChatbotContact.create({
                    'mobile_number': phone,
                    'partner_id': partner.id if partner else False,
                    'last_chatbot_id': self.chatbot_id.wa_chatbot_id.id,
                })
            self.wa_chatbot_contact_id = wa_contact

        # Log the message in our session transcript
        self._log_message('inbound', body)

        # Create a whatsapp.chatbot.message record; its create() override
        # triggers _handle_incoming_message() which runs the full step engine.
        wa_msg_vals = {
            'contact_id': wa_contact.id,
            'chatbot_id': self.chatbot_id.wa_chatbot_id.id,
            'type': 'incoming',
            'message_plain': body,
        }
        if cc_message and cc_message.whatsapp_message_id:
            wa_msg_vals['wa_message_id'] = cc_message.whatsapp_message_id.id

        try:
            self.env['whatsapp.chatbot.message'].sudo().create(wa_msg_vals)
        except Exception as e:
            _logger.error("Error dispatching WhatsApp chatbot step: %s", e)

        # Sync current step from WA contact
        if wa_contact.last_step_id:
            self.current_step_id = wa_contact.last_step_id
            if wa_contact.last_step_id.step_type == 'end_flow':
                self._finish_session()

    # -------------------------------------------------------------------------
    # Step processing – SMS / Email (text-only simplified runner)
    # -------------------------------------------------------------------------

    def _process_step_text(self, body):
        """
        Simplified step runner for non-WhatsApp channels.

        Supports:
        - message / question_* steps → send body_plain text, advance
        - set_variable → store value in collected_data
        - execute_code → run code, send result
        - end_flow → close session
        - Answer-based branching via trigger_answer_ids
        """
        self.ensure_one()
        wa_bot = self.chatbot_id.wa_chatbot_id
        self._log_message('inbound', body)

        step = self.current_step_id
        if not step:
            # Start from root steps
            roots = wa_bot.step_ids.filtered(lambda s: not s.parent_id).sorted('sequence')
            step = roots[:1]
            if not step:
                self._finish_session()
                return

        # Try to match an answer-based trigger first
        next_step = self._match_answer_trigger(step, body)

        if not next_step:
            # Default: first child, then next sibling
            children = step.child_ids.sorted('sequence')
            next_step = children[:1] if children else False

        if not next_step:
            self._finish_session()
            return

        self.current_step_id = next_step
        self._execute_text_step(next_step)

    def _match_answer_trigger(self, step, body):
        """Return the first child whose trigger_answer_ids match body."""
        body_l = (body or '').strip().lower()
        for child in step.child_ids.sorted('sequence'):
            for ans in child.trigger_answer_ids:
                if ans.value and ans.value.lower() in body_l:
                    return child
        return False

    def _execute_text_step(self, step):
        """Execute a single step for SMS/email and send the reply."""
        channel = self.channel
        contact = self.contact_id
        wa_bot = self.chatbot_id.wa_chatbot_id

        if step.step_type == 'end_flow':
            end_msg = self.chatbot_id.end_message
            if end_msg:
                self.chatbot_id._send_reply(contact, channel, end_msg)
            self._finish_session()
            return

        if step.step_type == 'set_variable' and step.variable_id:
            # Variable will be captured from the *next* inbound message;
            # store the step so the next call knows what to store.
            data = dict(self.collected_data or {})
            data['_pending_variable'] = step.variable_id.name
            self.collected_data = data

        if step.step_type == 'execute_code':
            result = step.execute_code(self)
            if result:
                self.chatbot_id._send_reply(contact, channel, str(result))
            # Auto-advance to first child
            next_child = step.child_ids.sorted('sequence')[:1]
            if next_child:
                self.current_step_id = next_child
                self._execute_text_step(next_child)
            else:
                self._finish_session()
            return

        # Render body – replace {{variables.*}} placeholders
        msg_text = step.body_plain or ''
        if msg_text:
            variables = self._get_variables_dict()
            msg_text = re.sub(
                r'\{\{variables\.([\w]+)\}\}',
                lambda m: str(variables.get(m.group(1), '')),
                msg_text,
            )
            self.chatbot_id._send_reply(contact, channel, msg_text)

        self._log_message('outbound', msg_text)

        # For question steps, we wait for inbound – don't auto-advance
        if step.step_type.startswith('question_'):
            return

        # For message/set_variable: auto-advance to first child
        next_child = step.child_ids.sorted('sequence')[:1]
        if next_child:
            self.current_step_id = next_child
            self._execute_text_step(next_child)
        else:
            self._finish_session()

    def _get_variables_dict(self):
        """Return {variable_name: value_str} from collected_data."""
        return {k: str(v) for k, v in (self.collected_data or {}).items() if not k.startswith('_')}

    def _finish_session(self):
        self.write({'state': 'completed'})

    def _log_message(self, direction, text):
        """Append a transcript entry."""
        self.env['contact.centre.chatbot.session.message'].sudo().create({
            'session_id': self.id,
            'direction': direction,
            'body': text or '',
        })


class ContactCentreChatbotSessionMessage(models.Model):
    """Lightweight transcript for a chatbot session (all channels)."""
    _name = 'contact.centre.chatbot.session.message'
    _description = 'Contact Centre Chatbot Session Message'
    _order = 'id asc'

    session_id = fields.Many2one('contact.centre.chatbot.session', 'Session',
                                 required=True, ondelete='cascade', index=True)
    direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], required=True)
    body = fields.Text('Message')
    create_date = fields.Datetime('Time', readonly=True)
