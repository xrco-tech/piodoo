# -*- coding: utf-8 -*-

import logging
import requests
import json
from odoo import models, fields, api
from odoo.fields import Datetime

_logger = logging.getLogger(__name__)


class WhatsAppTemplateSendWizard(models.TransientModel):
    _name = 'whatsapp.template.send.wizard'
    _description = 'WhatsApp Template Send Wizard'

    template_id = fields.Many2one('whatsapp.template', string='Template', required=True, readonly=True)
    recipient_phone = fields.Char(string='Recipient Phone', required=True,
                                 help='Phone number in international format (e.g., 27683264051)')
    phone_number_id = fields.Char(string='Phone Number ID', readonly=True)
    
    # Template parameters
    parameter_ids = fields.One2many('whatsapp.template.parameter', 'wizard_id', string='Parameters',
                                   help='Template parameters to fill placeholders')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_template_id'):
            template = self.env['whatsapp.template'].browse(self.env.context['default_template_id'])
            res['template_id'] = template.id
            res['phone_number_id'] = self.env['ir.config_parameter'].sudo().get_param('whatsapp_ligth.phone_number_id')
            
            # Create parameter records for placeholders
            import re
            placeholders = re.findall(r'\{\{(\d+)\}\}', template.body or '')
            if placeholders:
                parameters = []
                # Get unique placeholder numbers and sort them
                unique_placeholders = sorted(set(placeholders), key=int)
                for placeholder_num in unique_placeholders:
                    parameters.append((0, 0, {
                        'sequence': int(placeholder_num),
                        'placeholder': f'{{{{{placeholder_num}}}}}',
                        'value': '',
                    }))
                res['parameter_ids'] = parameters
        return res

    def action_send_template(self):
        """
        Send template message via WhatsApp API.
        """
        self.ensure_one()
        
        # Validate template is approved
        if self.template_id.status != 'APPROVED':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Template is not approved. Current status: {self.template_id.status}. Please wait for Meta to approve the template before sending.',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        if not self.recipient_phone.strip():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Please enter a recipient phone number.',
                    'type': 'danger',
                    'sticky': False,
                }
            }
        
        try:
            # Get access token
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            
            if not access_token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Format recipient phone
            recipient_phone = self.recipient_phone.replace('+', '').replace(' ', '').replace('-', '')
            
            # Build components with parameters
            components = []
            
            # Body parameters
            body_params = []
            for param in sorted(self.parameter_ids, key=lambda p: p.sequence):
                body_params.append({'type': 'text', 'text': param.value})
            
            if body_params:
                components.append({
                    'type': 'body',
                    'parameters': body_params
                })
            
            # Check if template is approved
            if self.template_id.status != 'APPROVED':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Template is not approved. Current status: {self.template_id.status}. Please wait for approval or submit the template first.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Build payload
            # Use the exact template name and language as submitted to Meta
            template_payload = {
                'name': self.template_id.name,
                'language': {'code': self.template_id.language},
                'components': components
            }
            
            # Add flow if template uses a flow
            if self.template_id.use_flow and self.template_id.flow_id:
                if self.template_id.flow_id.status != 'PUBLISHED':
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': f'Flow must be published before use. Current status: {self.template_id.flow_id.status}',
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
                
                # Add flow parameters to template
                template_payload['components'].append({
                    'type': 'FLOW',
                    'sub_type': 'FLOW',
                    'flow_id': self.template_id.flow_id.flow_id_meta,
                    'flow_token': '',  # Will be generated by Meta
                })
                
                if self.template_id.flow_id.first_page_id:
                    template_payload['components'][-1]['flow_first_page_id'] = self.template_id.flow_id.first_page_id
            
            payload = {
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': recipient_phone,
                'type': 'template',
                'template': template_payload
            }
            
            # Log template details for debugging
            _logger.info(f"Sending template: name={self.template_id.name}, language={self.template_id.language}, status={self.template_id.status}, meta_id={self.template_id.template_id_meta}, flow={self.template_id.flow_id.name if self.template_id.flow_id else 'None'}")
            
            # API endpoint
            url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            _logger.info(f"Sending template {self.template_id.name} to {recipient_phone}")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                message_id = response_data.get('messages', [{}])[0].get('id')
                
                # Update template usage
                self.template_id.write({
                    'usage_count': self.template_id.usage_count + 1,
                    'last_used': Datetime.now(),
                })
                
                # Create message record
                self.env['whatsapp.message'].sudo().create({
                    'message_id': message_id or f'template_{Datetime.now()}',
                    'wa_id': recipient_phone,
                    'phone_number': recipient_phone,
                    'contact_name': recipient_phone,
                    'message_type': 'template',
                    'message_body': self.template_id.body,
                    'template_name': self.template_id.name,
                    'template_language': self.template_id.language,
                    'message_timestamp': Datetime.now(),
                    'phone_number_id': self.phone_number_id,
                    'status': 'processed',
                    'is_incoming': False,
                })
                
                _logger.info(f"Template message sent successfully. Message ID: {message_id}")
                
                # Close the wizard
                return {'type': 'ir.actions.act_window_close'}
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                
                _logger.error(f"Failed to send template: {response.status_code} - {error_message}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to send template: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error sending template: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error sending template: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }


class WhatsAppTemplateParameter(models.TransientModel):
    _name = 'whatsapp.template.parameter'
    _description = 'WhatsApp Template Parameter'
    _order = 'sequence'

    wizard_id = fields.Many2one('whatsapp.template.send.wizard', string='Wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', required=True, default=1)
    placeholder = fields.Char(string='Placeholder', readonly=True)
    value = fields.Char(string='Value', required=True, help='Value to replace the placeholder')

    @api.model
    def create(self, vals):
        """Auto-set sequence if not provided"""
        if 'sequence' not in vals or not vals.get('sequence'):
            if vals.get('wizard_id'):
                # Get max sequence from existing parameters for this wizard
                wizard = self.env['whatsapp.template.send.wizard'].browse(vals['wizard_id'])
                max_seq = max([p.sequence for p in wizard.parameter_ids] + [0])
                vals['sequence'] = max_seq + 1
            else:
                vals['sequence'] = 1
        return super().create(vals)

