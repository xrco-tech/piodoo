# -*- coding: utf-8 -*-

import logging
import json
from odoo import http
from odoo.http import request
from markupsafe import Markup
from odoo.tools import html_sanitize

_logger = logging.getLogger(__name__)


class WhatsAppChatbotController(http.Controller):
    """
    Controller for handling WhatsApp chatbot functionality.
    Extends webhook processing to route messages to chatbots.
    """

    @http.route('/whatsapp/chatbot/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def chatbot_webhook(self):
        """
        Webhook endpoint specifically for chatbot message processing.
        This can be used as an alternative or extension to the main webhook.
        """
        try:
            import json
            data = request.httprequest.get_json(silent=True)
            
            if not data:
                raw_data = request.httprequest.get_data(as_text=True)
                data = json.loads(raw_data) if raw_data else {}
            
            _logger.info(f"Chatbot webhook received: {data}")
            
            # Process messages through chatbot system
            if data.get('object') == 'whatsapp_business_account':
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        
                        # Handle incoming messages
                        if 'messages' in value:
                            self._process_chatbot_messages(value['messages'], value, entry)
            
            return request.make_response('OK', [('Content-Type', 'text/plain')], status=200)
            
        except Exception as e:
            _logger.error(f"Error in chatbot webhook: {e}", exc_info=True)
            return request.make_response('Error', [('Content-Type', 'text/plain')], status=500)

    def _process_chatbot_messages(self, messages, value_data, entry_data):
        """
        Process incoming messages and route them to appropriate chatbots.
        
        :param messages: List of message objects from webhook
        :param value_data: The value object containing metadata and contacts
        :param entry_data: The entry object containing business account info
        """
        try:
            WhatsAppMessage = request.env['whatsapp.message'].sudo()
            ChatbotMessage = request.env['whatsapp.chatbot.message'].sudo()
            ChatbotContact = request.env['whatsapp.chatbot.contact'].sudo()
            
            for message in messages:
                _logger.info(f"Processing chatbot message: {message}")
                
                # First, create the whatsapp.message record (if not exists)
                message_id = message.get('id')
                wa_id = message.get('from')
                
                # Find or create WhatsApp message record
                wa_message = WhatsAppMessage.search([('message_id', '=', message_id)], limit=1)
                if not wa_message:
                    wa_message = WhatsAppMessage.create_from_webhook(message, value_data)
                
                if not wa_message:
                    _logger.error(f"Failed to create WhatsApp message: {message_id}")
                    continue
                
                # Find or create chatbot contact
                contacts = value_data.get('contacts', [])
                contact_data = contacts[0] if contacts else {}
                partner = self._find_or_create_partner(wa_id, contact_data)
                
                if not partner:
                    _logger.warning(f"Could not find or create partner for {wa_id}")
                    continue
                
                # Find chatbot contact
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
                    # Search for matching trigger (exact case-insensitive match)
                    # Use uppercase comparison for exact matching
                    matching_trigger = request.env['whatsapp.chatbot.trigger'].sudo().search([
                        ('name', '=', message_text.upper())
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
                    else:
                        # No trigger matched - don't assign a chatbot
                        # Only process messages that match triggers or are already in a conversation
                        _logger.info(f"No trigger matched for message '{message_text}'. Skipping chatbot processing.")
                        continue
                
                # Only continue if we have a chatbot (either from active conversation or trigger match)
                if not chatbot:
                    _logger.warning("No chatbot found to process message")
                    continue
                
                # Check if chatbot message already exists for this WhatsApp message
                # This prevents duplicate chatbot messages from the same WhatsApp message
                existing_chatbot_message = ChatbotMessage.sudo().search([
                    ('wa_message_id', '=', wa_message.id),
                    ('type', '=', 'incoming')
                ], limit=1)
                
                if existing_chatbot_message:
                    _logger.info(f"Chatbot message already exists for WhatsApp message {wa_message.id} (chatbot message ID: {existing_chatbot_message.id}). Skipping duplicate creation.")
                    continue
                
                # Create chatbot message record with duplicate handling for race conditions
                try:
                    message_body = wa_message.message_body or ''
                    chatbot_message = ChatbotMessage.create({
                        'contact_id': chatbot_contact.id,
                        'mobile_number': wa_id,
                        'chatbot_id': chatbot.id,
                        'wa_message_id': wa_message.id,
                        'message_plain': message_body,
                        'message_html': message_body,  # Simple conversion, can be enhanced
                        'type': 'incoming',
                    })
                    _logger.info(f"Created chatbot message: {chatbot_message.id}")
                except Exception as create_error:
                    # Handle race condition where another request created it first
                    error_str = str(create_error)
                    if 'duplicate' in error_str.lower() or 'unique constraint' in error_str.lower():
                        _logger.info(f"Chatbot message was created by another request for WhatsApp message {wa_message.id}, skipping")
                        continue
                    # Re-raise if it's a different error
                    raise
                
        except Exception as e:
            _logger.error(f"Error processing chatbot messages: {e}", exc_info=True)

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
            partner = request.env['res.partner'].sudo().search([
                '|',
                ('phone', '=', phone_number),
                ('mobile', '=', phone_number)
            ], limit=1)
            
            if not partner:
                # Create new partner
                name = contact_data.get('profile', {}).get('name', f"WhatsApp Contact {phone_number}")
                partner = request.env['res.partner'].sudo().create({
                    'name': name,
                    'mobile': phone_number,
                    'is_company': False,
                })
                _logger.info(f"Created new partner: {partner.id} for {phone_number}")
            
            return partner
            
        except Exception as e:
            _logger.error(f"Error finding/creating partner: {e}")
            return False

    @http.route('/chatbot/steps/<int:chatbot_id>', type='http', auth='user')
    def chatbot_steps(self, chatbot_id, **kw):
        """
        Display chatbot steps hierarchy in a visual tree/flow view.
        This route works with the website module installed.
        """
        try:
            chatbot = request.env['whatsapp.chatbot'].browse(chatbot_id).sudo()
            if not chatbot.exists():
                return request.not_found()
            
            Step = request.env['whatsapp.chatbot.step'].sudo()
            steps = Step.search([('chatbot_id', '=', chatbot.id)], order='parent_path, sequence, id')

            by_parent = {}
            for s in steps:
                by_parent.setdefault(s.parent_id.id if s.parent_id else 0, []).append(s)

            def build(node_id):
                nodes = []
                for s in by_parent.get(node_id, []):
                    show_preview = s.step_type not in ('execute_code', 'set_variable', 'end_flow')
                    preview_html = _preview_html(s) if show_preview else ""
                    
                    # Get answer triggers if any
                    answers = []
                    if hasattr(s, 'trigger_answer_ids') and s.trigger_answer_ids:
                        answers = s.trigger_answer_ids.mapped("display_name")
                    
                    # Variables are not stored as triggers in this model
                    variables = []
                    
                    nodes.append({
                        "id": s.id,
                        "name": s.name or f"Step #{s.id}",
                        "type": s.step_type or "",
                        "answers": answers,
                        "variables": variables,
                        "preview_html": preview_html,
                        "children": build(s.id),
                    })
                return nodes

            tree = build(0)
            return request.render('whatsapp_ligth_chatbot.chatbot_steps_tree_page', {
                "chatbot": chatbot,
                "chatbot_id": chatbot.id,
                "tree_json": Markup(json.dumps(tree, ensure_ascii=False)),
                "csrf_token": request.csrf_token(),
            })
        except Exception as e:
            _logger.error(f"Error rendering chatbot steps: {e}", exc_info=True)
            return request.not_found()

    @http.route('/chatbot/step/<int:step_id>/delete', type='http', auth='user', methods=['POST'], csrf=True)
    def chatbot_step_delete(self, step_id, **kw):
        """
        Delete a chatbot step. Returns JSON.
        Raises 400 with error message if the step has linked children steps.
        """
        try:
            step = request.env['whatsapp.chatbot.step'].browse(step_id)
            if not step.exists():
                return request.make_response(
                    json.dumps({'success': False, 'error': 'Step not found'}),
                    headers=[('Content-Type', 'application/json')],
                    status=404,
                )
            if step.child_ids:
                return request.make_response(
                    json.dumps({
                        'success': False,
                        'error': 'Cannot delete this step because it has linked child steps. Remove or reassign the child steps first.',
                    }),
                    headers=[('Content-Type', 'application/json')],
                    status=400,
                )
            step.unlink()
            return request.make_response(
                json.dumps({'success': True}),
                headers=[('Content-Type', 'application/json')],
                status=200,
            )
        except Exception as e:
            _logger.error(f"Error deleting chatbot step: {e}", exc_info=True)
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500,
            )


def _preview_html(step):
    """Take body_html or body_plain and sanitize it for safe embed."""
    src = step.body_html or step.body_plain or ''
    # Remove scripts/css, keep safe tags/attrs
    return html_sanitize(src or '')

