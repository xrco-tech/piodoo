# -*- coding: utf-8 -*-

import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppAuthController(http.Controller):

    @http.route('/whatsapp/auth/callback', type='http', auth='public', methods=['GET'], csrf=False)
    def oauth_callback(self, code=None, state=None, error=None, error_description=None):
        """
        OAuth callback endpoint for WhatsApp Meta Cloud API authentication.
        This endpoint receives the authorization code from Meta after user consent.
        
        :param code: Authorization code from Meta
        :param state: State parameter for CSRF protection
        :param error: Error code if authorization failed
        :param error_description: Error description if authorization failed
        """
        try:
            if error:
                _logger.error(f"WhatsApp OAuth error: {error} - {error_description}")
                return request.render('whatsapp_ligth.oauth_error', {
                    'error': error,
                    'error_description': error_description
                })

            if not code:
                _logger.error("WhatsApp OAuth callback received without authorization code")
                return request.render('whatsapp_ligth.oauth_error', {
                    'error': 'missing_code',
                    'error_description': 'Authorization code not provided'
                })

            # Get configuration parameters
            IrConfigParameter = request.env['ir.config_parameter'].sudo()
            app_id = IrConfigParameter.get_param('whatsapp_ligth.app_id')
            app_secret = IrConfigParameter.get_param('whatsapp_ligth.app_secret')
            redirect_uri = IrConfigParameter.get_param('whatsapp_ligth.redirect_uri', 
                                                       request.httprequest.url_root + 'whatsapp/auth/callback')

            if not app_id or not app_secret:
                _logger.error("WhatsApp app credentials not configured")
                return request.render('whatsapp_ligth.oauth_error', {
                    'error': 'configuration_error',
                    'error_description': 'WhatsApp app credentials not configured'
                })

            # Exchange authorization code for access token
            token_url = 'https://graph.facebook.com/v18.0/oauth/access_token'
            token_params = {
                'client_id': app_id,
                'client_secret': app_secret,
                'code': code,
                'redirect_uri': redirect_uri,
            }

            _logger.info("Exchanging authorization code for access token")
            response = requests.post(token_url, params=token_params, timeout=10)
            
            if response.status_code != 200:
                _logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return request.render('whatsapp_ligth.oauth_error', {
                    'error': 'token_exchange_failed',
                    'error_description': response.text
                })

            token_data = response.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                _logger.error(f"No access token in response: {token_data}")
                return request.render('whatsapp_ligth.oauth_error', {
                    'error': 'no_access_token',
                    'error_description': 'Access token not received from Meta'
                })

            # Store access token securely
            IrConfigParameter.set_param('whatsapp_ligth.access_token', access_token)
            
            # Optionally get long-lived token
            long_lived_token = self._get_long_lived_token(access_token, app_id, app_secret)
            if long_lived_token:
                IrConfigParameter.set_param('whatsapp_ligth.long_lived_token', long_lived_token)
                IrConfigParameter.set_param('whatsapp_ligth.access_token', long_lived_token)

            _logger.info("WhatsApp authentication successful")
            return request.render('whatsapp_ligth.oauth_success', {
                'message': 'WhatsApp authentication successful!'
            })

        except Exception as e:
            _logger.error(f"Error in WhatsApp OAuth callback: {e}", exc_info=True)
            return request.render('whatsapp_ligth.oauth_error', {
                'error': 'exception',
                'error_description': str(e)
            })

    def _get_long_lived_token(self, short_lived_token, app_id, app_secret):
        """
        Exchange short-lived token for long-lived token (60 days)
        
        :param short_lived_token: Short-lived access token
        :param app_id: Facebook App ID
        :param app_secret: Facebook App Secret
        :return: Long-lived access token or None
        """
        try:
            token_url = 'https://graph.facebook.com/v18.0/oauth/access_token'
            token_params = {
                'grant_type': 'fb_exchange_token',
                'client_id': app_id,
                'client_secret': app_secret,
                'fb_exchange_token': short_lived_token,
            }

            response = requests.get(token_url, params=token_params, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                return token_data.get('access_token')
            else:
                _logger.warning(f"Failed to get long-lived token: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Error getting long-lived token: {e}")
            return None

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def webhook(self):
        """
        Webhook endpoint for WhatsApp Meta Cloud API.
        Handles both verification (GET) and incoming messages (POST).
        """
        if request.httprequest.method == 'GET':
            # Webhook verification
            return self._verify_webhook()
        else:
            # Handle incoming webhook events
            return self._handle_webhook_event()

    def _verify_webhook(self):
        """
        Verify webhook with Meta's verification challenge.
        Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.
        """
        try:
            hub_mode = request.httprequest.args.get('hub.mode')
            hub_verify_token = request.httprequest.args.get('hub.verify_token')
            hub_challenge = request.httprequest.args.get('hub.challenge')

            _logger.info(f"Webhook verification request: mode={hub_mode}, token={hub_verify_token}")

            # Get configured verify token
            IrConfigParameter = request.env['ir.config_parameter'].sudo()
            verify_token = IrConfigParameter.get_param('whatsapp_ligth.webhook_verify_token')

            if hub_mode == 'subscribe' and hub_verify_token == verify_token:
                _logger.info("Webhook verification successful")
                return request.make_response(hub_challenge, [('Content-Type', 'text/plain')])
            else:
                _logger.warning(f"Webhook verification failed: mode={hub_mode}, token_match={hub_verify_token == verify_token}")
                return request.make_response('Verification failed', [('Content-Type', 'text/plain')], status=403)

        except Exception as e:
            _logger.error(f"Error in webhook verification: {e}", exc_info=True)
            return request.make_response('Error', [('Content-Type', 'text/plain')], status=500)

    def _handle_webhook_event(self):
        """
        Handle incoming webhook events from WhatsApp Meta Cloud API.
        Processes messages, status updates, etc.
        """
        try:
            # Parse JSON from request body
            import json
            data = request.httprequest.get_json(silent=True)
            
            if not data:
                # Fallback: try to parse from raw data
                try:
                    raw_data = request.httprequest.get_data(as_text=True)
                    data = json.loads(raw_data) if raw_data else {}
                except (json.JSONDecodeError, ValueError) as e:
                    _logger.error(f"Failed to parse webhook JSON: {e}")
                    return request.make_response('Invalid JSON', [('Content-Type', 'text/plain')], status=400)
            
            _logger.info(f"Received webhook event: {data}")

            # Meta sends events in this format:
            # {
            #   "object": "whatsapp_business_account",
            #   "entry": [...]
            # }

            if data.get('object') == 'whatsapp_business_account':
                for entry in data.get('entry', []):
                    # Store business account ID from entry if not already set
                    business_account_id = entry.get('id')
                    if business_account_id:
                        IrConfigParameter = request.env['ir.config_parameter'].sudo()
                        existing_ba_id = IrConfigParameter.get_param('whatsapp_ligth.business_account_id')
                        if not existing_ba_id:
                            IrConfigParameter.set_param('whatsapp_ligth.business_account_id', business_account_id)
                            _logger.info(f"Stored business account ID: {business_account_id}")
                    
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        
                        # Store phone_number_id from metadata if not already set
                        metadata = value.get('metadata', {})
                        phone_number_id = metadata.get('phone_number_id')
                        if phone_number_id:
                            IrConfigParameter = request.env['ir.config_parameter'].sudo()
                            existing_pn_id = IrConfigParameter.get_param('whatsapp_ligth.phone_number_id')
                            if not existing_pn_id:
                                IrConfigParameter.set_param('whatsapp_ligth.phone_number_id', phone_number_id)
                                _logger.info(f"Stored phone number ID: {phone_number_id}")
                        
                        # Handle messages
                        if 'messages' in value:
                            self._process_messages(value['messages'], value, entry)
                        
                        # Handle status updates
                        if 'statuses' in value:
                            self._process_statuses(value['statuses'])

            return request.make_response('OK', [('Content-Type', 'text/plain')], status=200)

        except Exception as e:
            _logger.error(f"Error handling webhook event: {e}", exc_info=True)
            return request.make_response('Error', [('Content-Type', 'text/plain')], status=500)

    def _process_messages(self, messages, value_data, entry_data):
        """
        Process incoming WhatsApp messages.
        
        :param messages: List of message objects from webhook
        :param value_data: The value object containing metadata and contacts
        :param entry_data: The entry object containing business account info
        """
        try:
            WhatsAppMessage = request.env['whatsapp.message'].sudo()
            
            for message in messages:
                _logger.info(f"Processing message: {message}")
                
                # Create message record in database
                message_record = WhatsAppMessage.create_from_webhook(message, value_data)
                
                if message_record:
                    _logger.info(f"Message saved with ID: {message_record.id}")
                    # Mark as processed
                    message_record.write({'status': 'processed'})
                else:
                    _logger.error(f"Failed to save message: {message.get('id', 'unknown')}")
                    
        except Exception as e:
            _logger.error(f"Error processing messages: {e}", exc_info=True)

    def _process_statuses(self, statuses):
        """
        Process message status updates (sent, delivered, read, etc.).
        
        :param statuses: List of status objects from webhook
        """
        try:
            for status in statuses:
                _logger.info(f"Processing status: {status}")
                # TODO: Implement status processing logic
                # Update message status in database, etc.
        except Exception as e:
            _logger.error(f"Error processing statuses: {e}", exc_info=True)

    @http.route('/whatsapp/auth/initiate', type='http', auth='user', methods=['GET'])
    def initiate_auth(self):
        """
        Initiate WhatsApp OAuth authentication flow.
        Redirects user to Meta's authorization page.
        """
        try:
            IrConfigParameter = request.env['ir.config_parameter'].sudo()
            app_id = IrConfigParameter.get_param('whatsapp_ligth.app_id')
            redirect_uri = IrConfigParameter.get_param('whatsapp_ligth.redirect_uri')
            if not redirect_uri:
                redirect_uri = request.httprequest.url_root + 'whatsapp/auth/callback'
                IrConfigParameter.set_param('whatsapp_ligth.redirect_uri', redirect_uri)
            scope = IrConfigParameter.get_param('whatsapp_ligth.scope')
            if not scope:
                scope = 'whatsapp_business_management,whatsapp_business_messaging'
                IrConfigParameter.set_param('whatsapp_ligth.scope', scope)

            if not app_id:
                return request.render('whatsapp_ligth.config_error', {
                    'message': 'WhatsApp App ID not configured. Please configure it in Settings.'
                })

            # Generate state for CSRF protection (optional but recommended)
            import secrets
            state = secrets.token_urlsafe(32)
            request.session['whatsapp_oauth_state'] = state

            # Build authorization URL
            auth_url = f"https://www.facebook.com/v18.0/dialog/oauth"
            params = {
                'client_id': app_id,
                'redirect_uri': redirect_uri,
                'scope': scope,
                'state': state,
                'response_type': 'code',
            }

            import urllib.parse
            auth_url_with_params = f"{auth_url}?{urllib.parse.urlencode(params)}"
            
            _logger.info(f"Initiating WhatsApp OAuth flow: {auth_url_with_params}")
            return request.redirect(auth_url_with_params)

        except Exception as e:
            _logger.error(f"Error initiating WhatsApp auth: {e}", exc_info=True)
            return request.render('whatsapp_ligth.config_error', {
                'message': f'Error initiating authentication: {str(e)}'
            })

