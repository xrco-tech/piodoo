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
    
    # Preview information
    preview_url = fields.Char(string='Preview URL', readonly=True,
                             help='URL to preview the flow')
    preview_url_expiry_date = fields.Datetime(string='Preview URL Expiry Date', readonly=True,
                                            help='When the preview URL expires')

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
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
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
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
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
            
            # Validate JSON first
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
            
            # Basic validation of flow structure
            validation_errors = []
            if 'version' not in flow_data:
                validation_errors.append("Missing required field: 'version'")
            if 'screens' not in flow_data:
                validation_errors.append("Missing required field: 'screens'")
            elif not isinstance(flow_data.get('screens'), list) or len(flow_data.get('screens', [])) == 0:
                validation_errors.append("'screens' must be a non-empty array")
            else:
                # Validate each screen has required fields
                for idx, screen in enumerate(flow_data.get('screens', [])):
                    if 'id' not in screen:
                        validation_errors.append(f"Screen {idx} is missing required field: 'id'")
                    if 'layout' not in screen:
                        validation_errors.append(f"Screen {idx} is missing required field: 'layout'")
            
            if validation_errors:
                error_msg = "Flow JSON validation errors:\n" + "\n".join(f"- {err}" for err in validation_errors)
                _logger.error(f"Flow JSON validation failed: {error_msg}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Validation Error',
                        'message': error_msg,
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Check current flow status from Meta before attempting to publish
            # This helps identify if the flow is in the correct state
            check_url = f"https://graph.facebook.com/v18.0/{self.flow_id_meta}?fields=id,name,status,version"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            _logger.info(f"Checking flow {self.flow_id_meta} status before publishing")
            check_response = requests.get(check_url, headers=headers, timeout=30)
            
            if check_response.status_code == 200:
                flow_info = check_response.json()
                current_status = flow_info.get('status', 'UNKNOWN')
                _logger.info(f"Flow current status: {current_status}")
                
                if current_status not in ('DRAFT', 'UNKNOWN'):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': f'Flow is in {current_status} status. Only DRAFT flows can be published. Please create a new version or reset the flow to DRAFT status.',
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
            else:
                _logger.warning(f"Could not check flow status: {check_response.status_code}")
            
            # Prepare headers for API calls
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            flow_url = f"https://graph.facebook.com/v18.0/{self.flow_id_meta}"
            
            # Filter flow_data to only include fields allowed in json_flow
            # According to Meta API, json_flow should only contain version and screens
            # Remove routing_model, data_api_version, and other metadata fields
            filtered_flow_data = {
                'version': flow_data.get('version'),
                'screens': flow_data.get('screens', []),
            }
            
            # Update and publish in one request
            # According to Meta docs, we can include both json_flow and status in the same request
            _logger.info(f"Updating and publishing flow {self.flow_id_meta}")
            
            publish_payload = {
                'json_flow': filtered_flow_data,
                'status': 'PUBLISHED',
            }
            
            # Add name and category if specified
            if self.name:
                publish_payload['name'] = self.name
            if self.category:
                publish_payload['categories'] = [self.category]
            
            _logger.debug(f"Publish URL: {flow_url}")
            _logger.debug(f"Publish payload keys: {list(publish_payload.keys())}")
            _logger.debug(f"Filtered flow data keys: {list(filtered_flow_data.keys())}")
            _logger.debug(f"Number of screens: {len(filtered_flow_data.get('screens', []))}")
            response = requests.post(flow_url, headers=headers, json=publish_payload, timeout=30)
            
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
                error_user_title = error_info.get('error_user_title', '')
                error_user_msg = error_info.get('error_user_msg', '')
                
                _logger.error(f"Failed to publish flow: {response.status_code} - {error_message} (Code: {error_code}, Subcode: {error_subcode})")
                _logger.error(f"Full error response: {json.dumps(error_data, indent=2)}")
                
                # Log the raw response for debugging
                _logger.error(f"Raw response text: {response.text}")
                
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

    def _get_flow_details(self, flow_id):
        """
        Get flow details from Meta API.
        """
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                      IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
        
        if not access_token:
            raise ValueError('Access token not configured')
        
        url = f"https://graph.facebook.com/v18.0/{flow_id}?fields=id,name,categories,preview,status,validation_errors,json_version,data_api_version,endpoint_uri"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_flow_assets(self, flow_id):
        """
        Get flow assets from Meta API.
        """
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                      IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
        
        if not access_token:
            raise ValueError('Access token not configured')
        
        url = f"https://graph.facebook.com/v18.0/{flow_id}/assets"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_flow_json(self, download_url):
        """
        Download flow JSON from the provided URL.
        """
        try:
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error fetching flow JSON from {download_url}: {e}")
            raise
    
    def action_fetch_from_meta(self):
        """
        Fetch flows from Meta API and sync with local records.
        This method fetches the flow JSON from Meta's assets API.
        """
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
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
                error_count = 0
                error_messages = []
                
                for flow_data in flows:
                    try:
                        flow_id = flow_data.get('id')
                        name = flow_data.get('name')
                        status = flow_data.get('status')
                        
                        # Find or create flow
                        flow = self.search([('flow_id_meta', '=', flow_id)], limit=1)
                        
                        # Get flow details (includes json_version, preview, etc.)
                        flow_details = self._get_flow_details(flow_id)
                        _logger.info(f"Flow details for {flow_id}: {flow_details}")
                        
                        # Get flow assets to find the JSON download URL
                        flow_assets = self._get_flow_assets(flow_id)
                        _logger.info(f"Flow assets for {flow_id}: {flow_assets}")
                        
                        # Find the FLOW_JSON asset
                        json_asset = None
                        if flow_assets.get('data'):
                            json_assets = [asset for asset in flow_assets['data'] if asset.get('asset_type') == 'FLOW_JSON']
                            if json_assets:
                                json_asset = json_assets[0]
                        
                        # Download the flow JSON
                        flow_json = None
                        if json_asset and json_asset.get('download_url'):
                            flow_json = self._get_flow_json(json_asset['download_url'])
                            _logger.info(f"Downloaded flow JSON for {flow_id}")
                        else:
                            _logger.warning(f"No FLOW_JSON asset found for flow {flow_id}")
                        
                        # Prepare values
                        vals = {
                            'flow_id_meta': flow_id,
                            'status': status,
                            'version': flow_details.get('json_version'),
                            'category': flow_data.get('categories', [None])[0] if flow_data.get('categories') else None,
                        }
                        
                        # Add flow JSON if we got it
                        if flow_json:
                            # Extract first page ID from screens
                            first_page_id = None
                            screens = flow_json.get('screens', [])
                            if screens:
                                first_page_id = screens[0].get('id')
                            
                            vals.update({
                                'flow_json': json.dumps(flow_json, indent=2),
                                'first_page_id': first_page_id,
                            })
                        
                        # Handle preview URL and expiry
                        preview = flow_details.get('preview', {})
                        if preview:
                            preview_url = preview.get('preview_url')
                            expires_at = preview.get('expires_at')
                            if preview_url:
                                vals['preview_url'] = preview_url
                            if expires_at:
                                try:
                                    from datetime import datetime
                                    expiry_datetime = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M:%S%z')
                                    vals['preview_url_expiry_date'] = expiry_datetime.strftime('%Y-%m-%d %H:%M:%S')
                                except Exception as e:
                                    _logger.warning(f"Could not parse expiry date {expires_at}: {e}")
                        
                        if flow:
                            # Update existing flow
                            flow.write(vals)
                            updated_count += 1
                            _logger.info(f"Updated flow {flow_id}: {name}")
                        else:
                            # Create new flow
                            if not name:
                                name = flow_id  # Fallback name
                            vals['name'] = name
                            self.create(vals)
                            created_count += 1
                            _logger.info(f"Created flow {flow_id}: {name}")
                    
                    except Exception as e:
                        error_count += 1
                        error_msg = f"Error syncing flow {flow_data.get('id', 'unknown')}: {str(e)}"
                        error_messages.append(error_msg)
                        _logger.error(error_msg, exc_info=True)
                
                # Build success message
                message = f'Synced flows: {created_count} created, {updated_count} updated.'
                if error_count > 0:
                    message += f' {error_count} errors occurred.'
                    if error_messages:
                        message += '\n\nErrors:\n' + '\n'.join(error_messages[:5])  # Show first 5 errors
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success' if error_count == 0 else 'Partial Success',
                        'message': message,
                        'type': 'success' if error_count == 0 else 'warning',
                        'sticky': error_count > 0,
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
            _logger.error(f"Error in action_fetch_from_meta: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Failed to sync flows: {str(e)}',
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

