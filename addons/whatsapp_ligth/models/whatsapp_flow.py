# -*- coding: utf-8 -*-

import logging
import requests
import json
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppFlow(models.Model):
    _name = 'whatsapp.flow'
    _description = 'WhatsApp Flow'
    _order = 'name, id desc'
    _rec_name = 'name'

    # Flow identifiers
    name = fields.Char(string='Flow Name', required=True, index=True,
                      help='Flow name (lowercase alphanumeric and underscores only)')
    flow_id_meta = fields.Char(string='Meta Flow ID', readonly=True,
                               help='Flow ID returned from Meta API')
    
    # Flow status
    status = fields.Selection([
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('DEPRECATED', 'Deprecated'),
        ('THROTTLED', 'Throttled'),
        ('BLOCKED', 'Blocked'),
    ], string='Status', readonly=True, default='DRAFT', index=True,
       help='Flow status: Draft (editing), Published (can be used), etc.')
    
    # Flow JSON definition
    flow_json = fields.Text(string='Flow JSON', required=True,
                            help='Flow definition in JSON format (screens, components, etc.)')
    flow_json_formatted = fields.Text(string='Flow JSON (Formatted)', compute='_compute_flow_json_formatted')
    
    # Flow metadata
    description = fields.Text(string='Description', help='Flow description for internal use')
    category = fields.Char(string='Category', help='Flow category (e.g., lead_generation, booking)')
    
    # Meta information
    version = fields.Char(string='Version', readonly=True, help='Flow version from Meta')
    created_time = fields.Datetime(string='Created Time', readonly=True)
    updated_time = fields.Datetime(string='Updated Time', readonly=True)
    
    # Usage tracking
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True,
                                help='Number of times this flow has been used')
    last_used = fields.Datetime(string='Last Used', readonly=True)
    
    # First page ID (needed for sending)
    first_page_id = fields.Char(string='First Page ID', readonly=True,
                               help='ID of the first screen/page in the flow')

    @api.depends('flow_json')
    def _compute_flow_json_formatted(self):
        """Format JSON for display"""
        for record in self:
            try:
                if record.flow_json:
                    parsed = json.loads(record.flow_json)
                    record.flow_json_formatted = json.dumps(parsed, indent=2)
                else:
                    record.flow_json_formatted = ''
            except (json.JSONDecodeError, ValueError):
                record.flow_json_formatted = record.flow_json or ''

    def action_create_flow_meta(self):
        """
        Create flow in Meta WhatsApp Business API.
        
        Based on: https://developers.facebook.com/docs/whatsapp/flows/gettingstarted
        """
        self.ensure_one()
        
        try:
            # Get access token and business account ID
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            business_account_id = IrConfigParameter.get_param('whatsapp_ligth.business_account_id')
            
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
            
            if not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Validate JSON
            try:
                flow_data = json.loads(self.flow_json)
            except json.JSONDecodeError as e:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Invalid JSON format: {str(e)}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Build payload
            payload = {
                'name': self.name,
                'categories': [self.category] if self.category else ['LEAD_GENERATION'],
                'endpoint_uri': '',  # Can be set for dynamic flows
                'json_flow': flow_data,
            }
            
            # API endpoint
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/flows"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            _logger.info(f"Creating flow {self.name} in Meta API")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code in (200, 201):
                response_data = response.json()
                flow_id = response_data.get('id')
                
                # Extract first page ID from flow JSON
                first_page_id = None
                try:
                    screens = flow_data.get('screens', [])
                    if screens:
                        first_page_id = screens[0].get('id')
                except:
                    pass
                
                self.write({
                    'flow_id_meta': flow_id,
                    'status': 'DRAFT',
                    'first_page_id': first_page_id,
                })
                
                _logger.info(f"Flow created successfully. Flow ID: {flow_id}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Flow created successfully! Flow ID: {flow_id}. Status: DRAFT. Publish it to use in templates.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                
                _logger.error(f"Failed to create flow: {response.status_code} - {error_message}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to create flow: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error creating flow: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error creating flow: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_publish_flow(self):
        """
        Publish flow in Meta API.
        Only published flows can be used in approved templates.
        
        Before publishing, the flow is updated with the latest JSON to ensure
        it's valid and in sync with Meta's servers.
        """
        self.ensure_one()
        
        if not self.flow_id_meta:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Flow must be created in Meta first before publishing.',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            business_account_id = IrConfigParameter.get_param('whatsapp_ligth.business_account_id')
            
            if not access_token or not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token or Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # First, update the flow with the latest JSON to ensure it's valid
            # This is required before publishing - Meta needs the flow to be up-to-date
            try:
                flow_data = json.loads(self.flow_json)
            except json.JSONDecodeError as e:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Invalid flow JSON format: {str(e)}. Please fix the JSON before publishing.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Update flow with latest JSON before publishing
            # This ensures Meta has the latest version and validates it
            update_url = f"https://graph.facebook.com/v18.0/{self.flow_id_meta}"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            # Build update payload with flow JSON
            update_payload = {
                'json_flow': flow_data,
            }
            
            # Add category if specified
            if self.category:
                update_payload['categories'] = [self.category]
            
            _logger.info(f"Updating flow {self.flow_id_meta} before publishing")
            _logger.debug(f"Update URL: {update_url}, Payload keys: {list(update_payload.keys())}")
            
            update_response = requests.post(update_url, headers=headers, json=update_payload, timeout=30)
            
            if update_response.status_code not in (200, 201):
                error_data = update_response.json() if update_response.text else {}
                error_info = error_data.get('error', {})
                error_message = error_info.get('message', update_response.text)
                _logger.warning(f"Flow update returned {update_response.status_code}: {error_message}")
                # Continue anyway - flow might already be up to date
            
            # Now publish the flow
            # According to Meta docs: POST /v18.0/{flow-id} with status in body
            publish_payload = {
                'status': 'PUBLISHED'
            }
            
            _logger.info(f"Publishing flow {self.flow_id_meta}")
            _logger.debug(f"Publish URL: {update_url}, Payload: {json.dumps(publish_payload, indent=2)}")
            response = requests.post(update_url, headers=headers, json=publish_payload, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                self.write({'status': 'PUBLISHED'})
                _logger.info(f"Flow published successfully. Response: {response_data}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': 'Flow published successfully! It can now be used in approved templates.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_info = error_data.get('error', {})
                error_message = error_info.get('message', response.text)
                error_code = error_info.get('code', 'Unknown')
                error_subcode = error_info.get('error_subcode', '')
                error_data_details = error_info.get('error_data', {})
                
                _logger.error(f"Failed to publish flow: {response.status_code} - {error_message} (Code: {error_code}, Subcode: {error_subcode})")
                _logger.debug(f"Full error response: {json.dumps(error_data, indent=2)}")
                
                # Provide more helpful error message based on error code and subcode
                if error_code == 100:
                    if error_subcode == 4233023:
                        detailed_msg = (
                            f"Invalid parameter error. Common causes:\n"
                            f"1. Flow JSON has validation errors - check all required fields are present\n"
                            f"2. Business account is not fully verified in Meta Business Manager\n"
                            f"3. Phone number display name is not approved\n"
                            f"4. Flow contains unsupported components or invalid values\n\n"
                            f"Error details: {error_message}"
                        )
                    else:
                        detailed_msg = f"Validation error: {error_message}. Ensure flow is in DRAFT status and has no validation errors."
                    
                    # Add error_data details if available
                    if error_data_details:
                        detailed_msg += f"\n\nAdditional details: {json.dumps(error_data_details, indent=2)}"
                elif 'parameter' in error_message.lower():
                    detailed_msg = f"Invalid parameter: {error_message}. Check that flow JSON is valid and all required fields are present."
                elif 'integrity' in error_message.lower() or 'verification' in error_message.lower():
                    detailed_msg = (
                        f"Integrity/Verification error: {error_message}\n\n"
                        f"Please ensure:\n"
                        f"1. Your WhatsApp Business Account is fully verified in Meta Business Manager\n"
                        f"2. Your phone number's display name is approved\n"
                        f"3. Your business verification is complete"
                    )
                else:
                    detailed_msg = f"{error_message} (Error Code: {error_code})"
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to publish flow: {detailed_msg}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error publishing flow: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error publishing flow: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_fetch_from_meta(self):
        """
        Fetch flows from Meta API and sync with local records.
        """
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('whatsapp_ligth.access_token') or \
                          IrConfigParameter.get_param('whatsapp_ligth.long_lived_token')
            business_account_id = IrConfigParameter.get_param('whatsapp_ligth.business_account_id')
            
            if not access_token or not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token or Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Fetch flows from Meta
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/flows"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                flows = data.get('data', [])
                
                created_count = 0
                updated_count = 0
                
                for flow_data in flows:
                    name = flow_data.get('name')
                    flow_id = flow_data.get('id')
                    status = flow_data.get('status')
                    
                    # Find or create flow
                    flow = self.search([('flow_id_meta', '=', flow_id)], limit=1)
                    
                    vals = {
                        'flow_id_meta': flow_id,
                        'status': status,
                        'version': flow_data.get('version'),
                    }
                    
                    if flow:
                        flow.write(vals)
                        updated_count += 1
                    else:
                        # Extract first page ID
                        first_page_id = None
                        json_flow = flow_data.get('json_flow', {})
                        screens = json_flow.get('screens', [])
                        if screens:
                            first_page_id = screens[0].get('id')
                        
                        vals.update({
                            'name': name,
                            'flow_json': json.dumps(json_flow, indent=2),
                            'first_page_id': first_page_id,
                            'category': flow_data.get('categories', [None])[0] if flow_data.get('categories') else None,
                        })
                        self.create(vals)
                        created_count += 1
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Synced flows: {created_count} created, {updated_count} updated.',
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
                        'message': f'Failed to fetch flows: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error fetching flows: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error fetching flows: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

