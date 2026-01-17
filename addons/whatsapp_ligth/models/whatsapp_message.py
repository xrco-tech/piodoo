# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api
from datetime import datetime

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _name = 'whatsapp.message'
    _description = 'WhatsApp Message'
    _order = 'message_timestamp desc, id desc'
    _rec_name = 'message_id'

    # Message identifiers
    message_id = fields.Char(string='Message ID', required=True, index=True, readonly=True)
    wa_id = fields.Char(string='WhatsApp ID', required=True, index=True, readonly=True, help='WhatsApp ID of the sender')
    phone_number = fields.Char(string='Phone Number', readonly=True, help='Phone number of the sender')
    
    # Contact information
    contact_name = fields.Char(string='Contact Name', readonly=True, help='Name from contact profile')
    
    # Message content
    message_type = fields.Char(string='Message Type', readonly=True, help='Type of message (text, image, etc.)')
    message_body = fields.Text(string='Message Body', readonly=True, help='Content of the message')
    raw_message_data = fields.Text(string='Raw Message Data', readonly=True, help='Complete raw message data as JSON')
    
    # Metadata
    message_timestamp = fields.Datetime(string='Message Timestamp', required=True, readonly=True, index=True)
    timestamp_unix = fields.Char(string='Unix Timestamp', readonly=True, help='Original Unix timestamp from webhook')
    
    # Business account info
    phone_number_id = fields.Char(string='Phone Number ID', readonly=True, help='Meta phone number ID')
    display_phone_number = fields.Char(string='Display Phone Number', readonly=True, help='Display phone number')
    business_account_id = fields.Char(string='Business Account ID', readonly=True, help='Meta business account ID')
    
    # Status tracking
    status = fields.Selection([
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('replied', 'Replied'),
        ('error', 'Error'),
    ], string='Status', default='received', readonly=True, index=True)
    
    # Additional fields
    is_incoming = fields.Boolean(string='Incoming Message', default=True, readonly=True, help='True if message is incoming, False if outgoing')
    error_message = fields.Text(string='Error Message', readonly=True, help='Error message if processing failed')

    _sql_constraints = [
        ('message_id_unique', 'unique(message_id)', 'Message ID must be unique!')
    ]

    @api.model
    def create_from_webhook(self, webhook_data, entry_data):
        """
        Create a WhatsApp message record from webhook data.
        
        :param webhook_data: The message data from webhook
        :param entry_data: The entry data containing metadata and contacts
        :return: Created message record
        """
        try:
            # Extract metadata
            metadata = entry_data.get('metadata', {})
            contacts = entry_data.get('contacts', [])
            contact = contacts[0] if contacts else {}
            
            # Extract message info
            message_id = webhook_data.get('id')
            wa_id = webhook_data.get('from')
            timestamp_str = webhook_data.get('timestamp')
            message_type = webhook_data.get('type', 'text')
            
            # Convert Unix timestamp to datetime
            message_timestamp = False
            if timestamp_str:
                try:
                    timestamp_int = int(timestamp_str)
                    message_timestamp = datetime.fromtimestamp(timestamp_int)
                except (ValueError, TypeError, OSError):
                    message_timestamp = fields.Datetime.now()
            else:
                message_timestamp = fields.Datetime.now()
            
            # Extract message body based on type
            message_body = ''
            if message_type == 'text':
                message_body = webhook_data.get('text', {}).get('body', '')
            elif message_type == 'image':
                message_body = f"Image: {webhook_data.get('image', {}).get('caption', 'No caption')}"
            elif message_type == 'document':
                message_body = f"Document: {webhook_data.get('document', {}).get('filename', 'Unknown')}"
            elif message_type == 'audio':
                message_body = "Audio message"
            elif message_type == 'video':
                message_body = f"Video: {webhook_data.get('video', {}).get('caption', 'No caption')}"
            else:
                message_body = f"{message_type} message"
            
            # Get contact name
            contact_name = contact.get('profile', {}).get('name', '')
            if not contact_name:
                contact_name = wa_id
            
            # Check if message already exists
            existing = self.search([('message_id', '=', message_id)], limit=1)
            if existing:
                _logger.info(f"Message {message_id} already exists, skipping")
                return existing
            
            # Create message record
            import json
            values = {
                'message_id': message_id,
                'wa_id': wa_id,
                'phone_number': wa_id,  # Use wa_id as phone number
                'contact_name': contact_name,
                'message_type': message_type,
                'message_body': message_body,
                'raw_message_data': json.dumps(webhook_data, indent=2),
                'message_timestamp': message_timestamp,
                'timestamp_unix': timestamp_str,
                'phone_number_id': metadata.get('phone_number_id', ''),
                'display_phone_number': metadata.get('display_phone_number', ''),
                'business_account_id': entry_data.get('id', ''),
                'status': 'received',
                'is_incoming': True,
            }
            
            message = self.create(values)
            return message
            
        except Exception as e:
            _logger.error(f"Error creating message from webhook: {e}", exc_info=True)
            # Try to create a minimal record with error status
            try:
                return self.create({
                    'message_id': webhook_data.get('id', f'error_{fields.Datetime.now()}'),
                    'wa_id': webhook_data.get('from', 'unknown'),
                    'message_type': webhook_data.get('type', 'unknown'),
                    'message_body': f'Error processing message: {str(e)}',
                    'message_timestamp': fields.Datetime.now(),
                    'status': 'error',
                    'error_message': str(e),
                    'is_incoming': True,
                })
            except:
                return False

    def send_whatsapp_message(self, recipient_phone, message_text, phone_number_id=None, context_message_id=None):
        """
        Send a WhatsApp message using Meta Cloud API.
        
        Based on: https://developers.facebook.com/documentation/business-messaging/whatsapp/overview
        
        :param recipient_phone: Recipient phone number in international format (e.g., '27683264051')
        :param message_text: Text content of the message
        :param phone_number_id: Phone number ID (optional, will use from config if not provided)
        :param context_message_id: Message ID to quote/reply to (optional, will show as quoted message)
        :return: Dictionary with success status and message ID or error
        """
        try:
            import requests
            import json
            
            # Get access token and phone number ID
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            
            if not access_token:
                return {
                    'success': False,
                    'error': 'Access token not configured. Please authenticate first.'
                }
            
            # Use provided phone_number_id or get from config
            if not phone_number_id:
                phone_number_id = IrConfigParameter.get_param('whatsapp_ligth.phone_number_id')
            
            if not phone_number_id:
                return {
                    'success': False,
                    'error': 'Phone number ID not configured.'
                }
            
            # Format recipient phone number (remove + and spaces)
            recipient_phone = recipient_phone.replace('+', '').replace(' ', '').replace('-', '')
            
            # API endpoint
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
            
            # Headers
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            # Message payload
            payload = {
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': recipient_phone,
                'type': 'text',
                'text': {
                    'preview_url': False,
                    'body': message_text
                }
            }
            
            # Add context to quote/reply to a message if provided
            if context_message_id:
                payload['context'] = {
                    'message_id': context_message_id
                }
                _logger.info(f"Including context message_id: {context_message_id} for quoted reply")
            
            _logger.info(f"Sending WhatsApp message to {recipient_phone} via {url}")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            # Send request
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id')
                
                _logger.info(f"Message sent successfully. Message ID: {message_id}")
                
                # Create outgoing message record (use sudo to ensure permissions)
                self.sudo().create({
                    'message_id': message_id or f'sent_{fields.Datetime.now()}',
                    'wa_id': recipient_phone,
                    'phone_number': recipient_phone,
                    'contact_name': recipient_phone,
                    'message_type': 'text',
                    'message_body': message_text,
                    'message_timestamp': fields.Datetime.now(),
                    'phone_number_id': phone_number_id,
                    'status': 'processed',
                    'is_incoming': False,
                })
                
                return {
                    'success': True,
                    'message_id': message_id,
                    'response': response_data
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                
                _logger.error(f"Failed to send message: {response.status_code} - {error_message}")
                
                return {
                    'success': False,
                    'error': error_message,
                    'status_code': response.status_code,
                    'response': error_data
                }
                
        except Exception as e:
            _logger.error(f"Error sending WhatsApp message: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def action_send_reply(self):
        """
        Action method to send a reply to the sender of this message.
        Opens a wizard or sends a quick reply.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send WhatsApp Reply',
            'res_model': 'whatsapp.message.reply.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message_id': self.id,
                'default_recipient_phone': self.wa_id,
                'default_phone_number_id': self.phone_number_id,
            }
        }

