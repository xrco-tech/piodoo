# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request

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
                
                # Determine which chatbot to use (for now, use the last active chatbot or first available)
                # In the future, this can be based on triggers, keywords, etc.
                chatbot = chatbot_contact.last_chatbot_id
                if not chatbot:
                    # Find first active chatbot (you can add more logic here)
                    chatbot = request.env['whatsapp.chatbot'].sudo().search([], limit=1)
                    if chatbot:
                        chatbot_contact.write({'last_chatbot_id': chatbot.id})
                
                if not chatbot:
                    _logger.warning("No chatbot found to process message")
                    continue
                
                # Create chatbot message record
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

