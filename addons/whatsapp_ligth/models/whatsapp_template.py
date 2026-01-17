# -*- coding: utf-8 -*-

import logging
import requests
import json
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'WhatsApp Message Template'
    _order = 'name, language'
    _rec_name = 'display_name'

    # Template identifiers
    name = fields.Char(string='Template Name', required=True, index=True,
                      help='Template name (lowercase alphanumeric and underscores only)')
    language = fields.Char(string='Language Code', required=True, default='en',
                          help='ISO 639 language code (e.g., en, es, fr)')
    category = fields.Selection([
        ('AUTHENTICATION', 'Authentication'),
        ('UTILITY', 'Utility'),
        ('MARKETING', 'Marketing'),
    ], string='Category', required=True, default='UTILITY',
       help='Template category: Authentication, Utility, or Marketing')
    
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    
    # Template components
    header_type = fields.Selection([
        ('TEXT', 'Text'),
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
        ('DOCUMENT', 'Document'),
    ], string='Header Type', help='Type of header component')
    header_text = fields.Text(string='Header Text', help='Text content for header (if header_type is TEXT)')
    header_media_handle = fields.Char(string='Header Media Handle', 
                                      help='Media handle for image/video/document header')
    
    body = fields.Text(string='Body', required=True,
                      help='Message body with placeholders {{1}}, {{2}}, etc.')
    footer = fields.Char(string='Footer', size=60,
                        help='Footer text (max 60 characters, no variables or emojis)')
    
    # Buttons
    button_ids = fields.One2many('whatsapp.template.button', 'template_id', string='Buttons',
                                help='Template buttons (quick reply, URL, phone number)')
    
    # Template status and metadata
    status = fields.Selection([
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('PAUSED', 'Paused'),
        ('PENDING_DELETION', 'Pending Deletion'),
        ('DISABLED', 'Disabled'),
    ], string='Status', readonly=True, default='PENDING', index=True)
    
    quality_score = fields.Selection([
        ('GREEN', 'High Quality'),
        ('YELLOW', 'Medium Quality'),
        ('RED', 'Low Quality'),
    ], string='Quality Score', readonly=True,
       help='Template quality rating based on user engagement')
    
    # Meta API fields
    template_id_meta = fields.Char(string='Meta Template ID', readonly=True,
                                  help='Template ID returned from Meta API')
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True,
                                  help='Reason if template was rejected')
    
    # Additional info
    description = fields.Text(string='Description', help='Template description for internal use')
    example_data = fields.Text(string='Example Data', 
                              help='Example JSON data for template parameters')
    
    # Usage tracking
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True,
                                help='Number of times this template has been used')
    last_used = fields.Datetime(string='Last Used', readonly=True)
    
    _sql_constraints = [
        ('name_language_unique', 'unique(name, language)', 'Template name and language combination must be unique!')
    ]

    @api.depends('name', 'language')
    def _compute_display_name(self):
        """Compute display name for template"""
        for record in self:
            record.display_name = f"{record.name} ({record.language})"

    def action_submit_to_meta(self):
        """
        Submit template to Meta WhatsApp Business API for approval.
        
        Based on: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview
        """
        self.ensure_one()
        
        try:
            # Get access token and phone number ID
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            phone_number_id = IrConfigParameter.get_param('whatsapp_ligth.phone_number_id')
            
            if not access_token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token not configured. Please authenticate first.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            if not phone_number_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Phone number ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Build template components
            components = []
            
            # Header component
            if self.header_type:
                header_component = {'type': 'HEADER'}
                if self.header_type == 'TEXT':
                    header_component['format'] = 'TEXT'
                    header_component['text'] = self.header_text
                elif self.header_type in ('IMAGE', 'VIDEO', 'DOCUMENT'):
                    header_component['format'] = self.header_type
                    if self.header_media_handle:
                        header_component['example'] = {'header_handle': [self.header_media_handle]}
                components.append(header_component)
            
            # Body component
            body_component = {
                'type': 'BODY',
                'text': self.body,
            }
            # Extract example parameters from body placeholders
            example_params = self._extract_example_params()
            if example_params:
                body_component['example'] = {'body_text': [example_params]}
            components.append(body_component)
            
            # Footer component
            if self.footer:
                components.append({
                    'type': 'FOOTER',
                    'text': self.footer
                })
            
            # Button components (group all buttons into one BUTTONS component)
            if self.button_ids:
                buttons_list = []
                for button in self.button_ids:
                    if button.button_type == 'QUICK_REPLY':
                        buttons_list.append({
                            'type': 'QUICK_REPLY',
                            'text': button.text
                        })
                    elif button.button_type == 'URL':
                        buttons_list.append({
                            'type': 'URL',
                            'text': button.text,
                            'url': button.url
                        })
                    elif button.button_type == 'PHONE_NUMBER':
                        buttons_list.append({
                            'type': 'PHONE_NUMBER',
                            'text': button.text,
                            'phone_number': button.phone_number
                        })
                
                if buttons_list:
                    components.append({
                        'type': 'BUTTONS',
                        'buttons': buttons_list
                    })
            
            # Build payload
            payload = {
                'name': self.name,
                'language': self.language,
                'category': self.category,
                'components': components
            }
            
            # API endpoint
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}/message_templates"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            _logger.info(f"Submitting template {self.name} to Meta API")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code in (200, 201):
                response_data = response.json()
                template_id = response_data.get('id')
                
                self.write({
                    'template_id_meta': template_id,
                    'status': 'PENDING',
                })
                
                _logger.info(f"Template submitted successfully. Template ID: {template_id}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Template submitted successfully! Template ID: {template_id}. Awaiting approval.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                
                _logger.error(f"Failed to submit template: {response.status_code} - {error_message}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to submit template: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error submitting template: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error submitting template: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _extract_example_params(self):
        """
        Extract example parameters from body text placeholders.
        Returns a list of example values for placeholders.
        """
        if not self.body:
            return []
        
        import re
        # Find all placeholders like {{1}}, {{2}}, etc.
        placeholders = re.findall(r'\{\{(\d+)\}\}', self.body)
        if not placeholders:
            return []
        
        # Return example values
        examples = []
        for i in range(1, len(placeholders) + 1):
            examples.append(f"Example {i}")
        return examples

    def action_fetch_from_meta(self):
        """
        Fetch templates from Meta API and sync with local records.
        """
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            phone_number_id = IrConfigParameter.get_param('whatsapp_ligth.phone_number_id')
            
            if not access_token or not phone_number_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token or phone number ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Fetch templates from Meta
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}/message_templates"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                templates = data.get('data', [])
                
                created_count = 0
                updated_count = 0
                
                for template_data in templates:
                    name = template_data.get('name')
                    language = template_data.get('language')
                    status = template_data.get('status')
                    quality = template_data.get('quality')
                    
                    # Find or create template
                    template = self.search([
                        ('name', '=', name),
                        ('language', '=', language)
                    ], limit=1)
                    
                    vals = {
                        'template_id_meta': template_data.get('id'),
                        'status': status,
                        'quality_score': quality,
                        'category': template_data.get('category', 'UTILITY'),
                    }
                    
                    if template:
                        template.write(vals)
                        updated_count += 1
                    else:
                        # Extract components
                        components = template_data.get('components', [])
                        body_text = ''
                        footer_text = ''
                        header_type = False
                        header_text = ''
                        
                        for component in components:
                            if component.get('type') == 'BODY':
                                body_text = component.get('text', '')
                            elif component.get('type') == 'FOOTER':
                                footer_text = component.get('text', '')
                            elif component.get('type') == 'HEADER':
                                header_format = component.get('format')
                                if header_format == 'TEXT':
                                    header_type = 'TEXT'
                                    header_text = component.get('text', '')
                                elif header_format in ('IMAGE', 'VIDEO', 'DOCUMENT'):
                                    header_type = header_format
                        
                        vals.update({
                            'name': name,
                            'language': language,
                            'body': body_text,
                            'footer': footer_text,
                            'header_type': header_type,
                            'header_text': header_text,
                        })
                        self.create(vals)
                        created_count += 1
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Synced templates: {created_count} created, {updated_count} updated.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to fetch templates: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error fetching templates: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error fetching templates: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_send_template(self):
        """
        Action to send a template message.
        Opens a wizard to compose and send template message.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Template Message',
            'res_model': 'whatsapp.template.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.id,
            }
        }


class WhatsAppTemplateButton(models.Model):
    _name = 'whatsapp.template.button'
    _description = 'WhatsApp Template Button'
    _order = 'sequence, id'

    template_id = fields.Many2one('whatsapp.template', string='Template', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    button_type = fields.Selection([
        ('QUICK_REPLY', 'Quick Reply'),
        ('URL', 'URL'),
        ('PHONE_NUMBER', 'Phone Number'),
    ], string='Button Type', required=True, default='QUICK_REPLY')
    text = fields.Char(string='Button Text', required=True, size=25,
                     help='Button label (max 25 characters)')
    url = fields.Char(string='URL', help='URL for URL button type')
    phone_number = fields.Char(string='Phone Number', help='Phone number for PHONE_NUMBER button type')

