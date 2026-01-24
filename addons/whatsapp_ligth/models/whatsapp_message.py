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
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
        ('location', 'Location'),
        ('contacts', 'Contacts'),
        ('interactive', 'Interactive'),
        ('template', 'Template'),
        ('sticker', 'Sticker'),
        ('reaction', 'Reaction'),
        ('unknown', 'Unknown'),
    ], string='Message Type', readonly=True, default='text', index=True)
    message_body = fields.Text(string='Message Body', readonly=True, help='Content of the message')
    raw_message_data = fields.Text(string='Raw Message Data', readonly=True, help='Complete raw message data as JSON')
    
    # Text message fields
    text_preview_url = fields.Boolean(string='Preview URL', readonly=True, help='Whether URL preview is enabled')
    
    # Media message fields (image, video, audio, document)
    media_id = fields.Char(string='Media ID', readonly=True, help='Media ID from WhatsApp')
    media_url = fields.Char(string='Media URL', readonly=True, help='URL to download media')
    media_mime_type = fields.Char(string='MIME Type', readonly=True, help='MIME type of media')
    media_sha256 = fields.Char(string='SHA256 Hash', readonly=True, help='SHA256 hash of media')
    media_size = fields.Integer(string='Media Size (bytes)', readonly=True, help='Size of media in bytes')
    media_attachment_id = fields.Many2one('ir.attachment', string='Media Attachment', readonly=True,
                                          help='Downloaded media stored as attachment')
    
    # Image/Video specific fields
    caption = fields.Text(string='Caption', readonly=True, help='Caption for image/video')
    image_width = fields.Integer(string='Image Width', readonly=True)
    image_height = fields.Integer(string='Image Height', readonly=True)
    
    # Document specific fields
    document_filename = fields.Char(string='Filename', readonly=True, help='Document filename')
    
    # Audio specific fields
    audio_voice = fields.Boolean(string='Voice Message', readonly=True, help='Whether audio is a voice message')
    
    # Location message fields
    location_latitude = fields.Float(string='Latitude', readonly=True, digits=(10, 7))
    location_longitude = fields.Float(string='Longitude', readonly=True, digits=(10, 7))
    location_name = fields.Char(string='Location Name', readonly=True)
    location_address = fields.Text(string='Location Address', readonly=True)
    
    # Contact message fields
    contact_data = fields.Text(string='Contact Data', readonly=True, help='JSON data for contacts')
    
    # Interactive message fields
    interactive_type = fields.Char(string='Interactive Type', readonly=True, help='Type of interactive message (button, list, etc.)')
    interactive_data = fields.Text(string='Interactive Data', readonly=True, help='JSON data for interactive message')
    
    # Template message fields
    template_name = fields.Char(string='Template Name', readonly=True)
    template_language = fields.Char(string='Template Language', readonly=True)
    template_params = fields.Text(string='Template Parameters', readonly=True, help='JSON parameters for template')
    
    # Context/Quoted message fields
    context_message_id = fields.Char(string='Context Message ID', readonly=True, 
                                    help='ID of the message being replied to/quoted')
    context_from = fields.Char(string='Context From', readonly=True, 
                              help='Sender of the quoted message')
    context_referred_product_id = fields.Char(string='Referred Product ID', readonly=True,
                                             help='Product ID if message is product-related')
    has_context = fields.Boolean(string='Is Reply/Quote', compute='_compute_has_context', store=True,
                                help='Whether this message is a reply to another message')
    
    # Reaction message fields
    reaction_message_id = fields.Char(string='Reaction Message ID', readonly=True,
                                     help='ID of the message being reacted to')
    reaction_emoji = fields.Char(string='Reaction Emoji', readonly=True, help='Emoji used in reaction')
    
    # Message status fields (from status webhooks)
    message_status = fields.Selection([
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
        ('deleted', 'Deleted'),
    ], string='Message Status', readonly=True, index=True, help='Current delivery status of the message')
    status_timestamp = fields.Datetime(string='Status Timestamp', readonly=True,
                                      help='Timestamp when status was last updated')
    status_recipient_id = fields.Char(string='Status Recipient ID', readonly=True,
                                     help='Recipient ID for status updates')
    status_error_code = fields.Integer(string='Error Code', readonly=True,
                                      help='Error code if message failed')
    status_error_title = fields.Char(string='Error Title', readonly=True, help='Error title if message failed')
    status_error_message = fields.Text(string='Error Message', readonly=True, help='Error message if message failed')
    
    # Pricing information
    pricing_category = fields.Char(string='Pricing Category', readonly=True,
                                  help='Pricing category (e.g., business_initiated, user_initiated)')
    pricing_model = fields.Char(string='Pricing Model', readonly=True, help='Pricing model')
    
    # Preview field
    message_preview_html = fields.Html(string='Message Preview', compute='_compute_message_preview_html', sanitize=False)
    
    @api.depends('message_body', 'message_type', 'is_incoming', 'message_timestamp', 
                 'location_name', 'location_address', 'document_filename', 'audio_voice',
                 'caption', 'template_name', 'reaction_emoji')
    def _compute_message_preview_html(self):
        """Compute HTML preview of the message using QWeb template"""
        for record in self:
            try:
                # Choose template based on message direction
                template_name = 'whatsapp_ligth.whatsapp_message_preview_received' if record.is_incoming else 'whatsapp_ligth.whatsapp_message_preview'
                
                # Use ir.ui.view to render the template
                preview = self.env['ir.ui.view']._render_template(template_name, {
                    'message_body': record.message_body or '',
                    'message_type': record.message_type or 'text',
                    'is_incoming': record.is_incoming,
                    'message_timestamp': record.message_timestamp.strftime('%H:%M') if record.message_timestamp else '',
                    'location_name': record.location_name or '',
                    'location_address': record.location_address or '',
                    'document_filename': record.document_filename or '',
                    'audio_voice': record.audio_voice,
                    'caption': record.caption or '',
                    'template_name': record.template_name or '',
                    'reaction_emoji': record.reaction_emoji or '',
                })
                record.message_preview_html = preview.decode('utf-8') if isinstance(preview, bytes) else preview
            except Exception as e:
                _logger.warning(f"Error rendering message preview: {e}", exc_info=True)
                record.message_preview_html = f'<div>Error rendering preview: {str(e)}</div>'
    
    @api.depends('context_message_id')
    def _compute_has_context(self):
        """Compute whether message has context (is a reply/quote)"""
        for record in self:
            record.has_context = bool(record.context_message_id)

    def _download_and_store_media(self, media_id, media_type='image', filename=None):
        """
        Download media from WhatsApp API and store as attachment.
        
        Based on: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media
        
        :param media_id: Media ID from WhatsApp
        :param media_type: Type of media (image, video, audio, document, sticker)
        :param filename: Optional filename for the attachment
        :return: ir.attachment record or False
        """
        try:
            import requests
            import base64
            
            if not media_id:
                return False
            
            # Get access token
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            
            if not access_token:
                _logger.error("Access token not configured for media download")
                return False
            
            # Step 1: Get media URL from WhatsApp API
            media_url_endpoint = f"https://graph.facebook.com/v18.0/{media_id}"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            _logger.info(f"Fetching media URL for media_id: {media_id}")
            response = requests.get(media_url_endpoint, headers=headers, timeout=30)
            
            if response.status_code != 200:
                _logger.error(f"Failed to get media URL: {response.status_code} - {response.text}")
                return False
            
            media_info = response.json()
            download_url = media_info.get('url')
            mime_type = media_info.get('mime_type', 'application/octet-stream')
            file_size = media_info.get('file_size', 0)
            sha256 = media_info.get('sha256')
            
            if not download_url:
                _logger.error("No download URL in media info response")
                return False
            
            # Step 2: Download the media binary content
            _logger.info(f"Downloading media from: {download_url}")
            download_response = requests.get(download_url, headers=headers, timeout=60)
            
            if download_response.status_code != 200:
                _logger.error(f"Failed to download media: {download_response.status_code}")
                return False
            
            media_content = download_response.content
            
            # Generate filename if not provided
            if not filename:
                extension_map = {
                    'image': 'jpg',
                    'video': 'mp4',
                    'audio': 'mp3',
                    'document': 'pdf',
                    'sticker': 'webp',
                }
                extension = extension_map.get(media_type, 'bin')
                # Try to get extension from mime type
                if mime_type:
                    mime_extensions = {
                        'image/jpeg': 'jpg',
                        'image/png': 'png',
                        'image/gif': 'gif',
                        'image/webp': 'webp',
                        'video/mp4': 'mp4',
                        'video/quicktime': 'mov',
                        'audio/mpeg': 'mp3',
                        'audio/ogg': 'ogg',
                        'application/pdf': 'pdf',
                        'application/msword': 'doc',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                    }
                    extension = mime_extensions.get(mime_type, extension)
                filename = f"whatsapp_{media_type}_{self.message_id or 'media'}.{extension}"
            
            # Step 3: Create attachment
            attachment_vals = {
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(media_content).decode('utf-8'),
                'mimetype': mime_type,
                'res_model': 'whatsapp.message',
                'res_id': self.id,
            }
            
            attachment = self.env['ir.attachment'].sudo().create(attachment_vals)
            _logger.info(f"Created attachment {attachment.id} for media {media_id}")
            
            return attachment
            
        except Exception as e:
            _logger.error(f"Error downloading and storing media: {e}", exc_info=True)
            return False
    
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
            
            # Extract message body and type-specific data
            message_body = ''
            media_id = None
            media_url = None
            media_mime_type = None
            media_sha256 = None
            media_size = None
            caption = None
            image_width = None
            image_height = None
            document_filename = None
            audio_voice = False
            location_latitude = None
            location_longitude = None
            location_name = None
            location_address = None
            contact_data = None
            interactive_type = None
            interactive_data = None
            template_name = None
            template_language = None
            template_params = None
            context_message_id = None
            context_from = None
            context_referred_product_id = None
            reaction_message_id = None
            reaction_emoji = None
            text_preview_url = False
            
            # Extract context if present
            context = webhook_data.get('context', {})
            if context:
                context_message_id = context.get('message_id')
                context_from = context.get('from')
                context_referred_product_id = context.get('referred_product', {}).get('product_retailer_id')
            
            # Extract data based on message type
            if message_type == 'text':
                text_data = webhook_data.get('text', {})
                message_body = text_data.get('body', '')
                text_preview_url = text_data.get('preview_url', False)
            elif message_type == 'image':
                image_data = webhook_data.get('image', {})
                message_body = f"Image: {image_data.get('caption', 'No caption')}"
                caption = image_data.get('caption')
                media_id = image_data.get('id')
                media_mime_type = image_data.get('mime_type')
                media_sha256 = image_data.get('sha256')
                media_size = image_data.get('file_size')
                image_width = image_data.get('width')
                image_height = image_data.get('height')
            elif message_type == 'video':
                video_data = webhook_data.get('video', {})
                message_body = f"Video: {video_data.get('caption', 'No caption')}"
                caption = video_data.get('caption')
                media_id = video_data.get('id')
                media_mime_type = video_data.get('mime_type')
                media_sha256 = video_data.get('sha256')
                media_size = video_data.get('file_size')
            elif message_type == 'audio':
                audio_data = webhook_data.get('audio', {})
                message_body = "Audio message"
                media_id = audio_data.get('id')
                media_mime_type = audio_data.get('mime_type')
                media_sha256 = audio_data.get('sha256')
                media_size = audio_data.get('file_size')
                audio_voice = audio_data.get('voice', False)
            elif message_type == 'document':
                doc_data = webhook_data.get('document', {})
                document_filename = doc_data.get('filename', 'Unknown')
                message_body = f"Document: {document_filename}"
                media_id = doc_data.get('id')
                media_mime_type = doc_data.get('mime_type')
                media_sha256 = doc_data.get('sha256')
                media_size = doc_data.get('file_size')
                caption = doc_data.get('caption')
            elif message_type == 'location':
                loc_data = webhook_data.get('location', {})
                location_latitude = loc_data.get('latitude')
                location_longitude = loc_data.get('longitude')
                location_name = loc_data.get('name')
                location_address = loc_data.get('address')
                message_body = f"Location: {location_name or f'{location_latitude}, {location_longitude}'}"
            elif message_type == 'contacts':
                contacts_data = webhook_data.get('contacts', [])
                import json
                contact_data = json.dumps(contacts_data, indent=2) if contacts_data else None
                message_body = f"Contact(s): {len(contacts_data)} contact(s) shared"
            elif message_type == 'interactive':
                interactive_data_obj = webhook_data.get('interactive', {})
                interactive_type = interactive_data_obj.get('type')
                import json
                interactive_data = json.dumps(interactive_data_obj, indent=2)
                message_body = f"Interactive: {interactive_type}"
            elif message_type == 'template':
                template_data = webhook_data.get('template', {})
                template_name = template_data.get('name')
                template_language = template_data.get('language')
                import json
                template_params = json.dumps(template_data.get('components', []), indent=2)
                message_body = f"Template: {template_name}"
            elif message_type == 'sticker':
                sticker_data = webhook_data.get('sticker', {})
                media_id = sticker_data.get('id')
                media_mime_type = sticker_data.get('mime_type')
                media_sha256 = sticker_data.get('sha256')
                media_size = sticker_data.get('file_size')
                message_body = "Sticker"
            elif message_type == 'reaction':
                reaction_data = webhook_data.get('reaction', {})
                reaction_message_id = reaction_data.get('message_id')
                reaction_emoji = reaction_data.get('emoji')
                message_body = f"Reaction: {reaction_emoji}"
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
                # Text fields
                'text_preview_url': text_preview_url,
                # Media fields
                'media_id': media_id,
                'media_mime_type': media_mime_type,
                'media_sha256': media_sha256,
                'media_size': media_size,
                # Image/Video fields
                'caption': caption,
                'image_width': image_width,
                'image_height': image_height,
                # Document fields
                'document_filename': document_filename,
                # Audio fields
                'audio_voice': audio_voice,
                # Location fields
                'location_latitude': location_latitude,
                'location_longitude': location_longitude,
                'location_name': location_name,
                'location_address': location_address,
                # Contact fields
                'contact_data': contact_data,
                # Interactive fields
                'interactive_type': interactive_type,
                'interactive_data': interactive_data,
                # Template fields
                'template_name': template_name,
                'template_language': template_language,
                'template_params': template_params,
                # Context fields
                'context_message_id': context_message_id,
                'context_from': context_from,
                'context_referred_product_id': context_referred_product_id,
                # Reaction fields
                'reaction_message_id': reaction_message_id,
                'reaction_emoji': reaction_emoji,
            }
            
            message = self.create(values)
            
            # Download and store media if present
            if media_id and message_type in ('image', 'video', 'audio', 'document', 'sticker'):
                _logger.info(f"Downloading media for message {message_id}")
                attachment = message._download_and_store_media(
                    media_id=media_id,
                    media_type=message_type,
                    filename=document_filename if message_type == 'document' else None
                )
                if attachment:
                    message.write({'media_attachment_id': attachment.id})
                    _logger.info(f"Media downloaded and stored as attachment {attachment.id}")
                else:
                    _logger.warning(f"Failed to download media for message {message_id}")
            
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

