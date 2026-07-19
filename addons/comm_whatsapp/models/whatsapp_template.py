# -*- coding: utf-8 -*-

import logging
import requests
import json
import re
from odoo import models, fields, api
from markupsafe import Markup

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

    # WABA account this template lives on. Left empty for pre-account
    # installs; syncing from an account form auto-tags imports with the
    # originating account so per-WABA counts / filters work.
    account_id = fields.Many2one(
        'comm.whatsapp.account', string='WhatsApp Account',
        ondelete='restrict',
        help="Pick the WABA account that owns this template. When left empty, "
             "the legacy comm_whatsapp.* system parameters are used for Meta "
             "operations.",
    )
    
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

    # Call permission request — a distinct Meta component type (not a
    # button) that renders Meta's own native accept/decline calling UI.
    # Mutually exclusive with button_ids: Meta rejects a template that
    # combines call_permission_request with other interactive components.
    is_call_permission_request = fields.Boolean(
        string='Call Permission Request',
        help="Adds Meta's call_permission_request component, letting the "
             "recipient grant this business permission to call them on "
             "WhatsApp directly from the message. Category must be "
             "UTILITY or MARKETING, and the template cannot also have "
             "buttons.",
    )

    # Flow integration
    flow_id = fields.Many2one('whatsapp.flow', string='Flow', 
                             help='WhatsApp Flow to attach to this template (for interactive experiences)')
    use_flow = fields.Boolean(string='Use Flow', default=False,
                             help='Enable to send this template with an attached flow')
    
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
    
    # Preview field
    template_preview_html = fields.Html(string='Template Preview', compute='_compute_template_preview_html', sanitize=False)
    
    _sql_constraints = [
        # A template's natural key is (WABA, name, language). Two WABAs can
        # legitimately host their own "welcome/en" template. Legacy rows
        # without an account (NULL) coexist with newly-tagged ones.
        ('name_language_account_unique',
         'unique(account_id, name, language)',
         'Template name and language must be unique per WhatsApp account!'),
    ]

    @api.depends('name', 'language')
    def _compute_display_name(self):
        """Compute display name for template"""
        for record in self:
            record.display_name = f"{record.name} ({record.language})"
    
    def _format_whatsapp_text(self, text):
        """
        Format WhatsApp text with styling markers to HTML.
        WhatsApp formatting:
        - *text* for bold
        - _text_ for italic
        - ~text~ for strikethrough
        - ```text``` for monospace
        - > text for blockquotes (at start of line)
        """
        if not text:
            return ''
        
        text = str(text)
        
        # Handle blockquotes first (lines starting with >)
        # Split by newlines, process each line
        lines = text.split('\n')
        formatted_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith('>'):
                # Blockquote line - remove > and format
                quote_text = stripped[1:].strip()
                # Escape the quote text using Markup.escape() class method
                quote_text = Markup.escape(quote_text)
                formatted_lines.append(f'<div style="border-left: 3px solid #075E54; padding-left: 8px; margin: 4px 0; color: #666;">{quote_text}</div>')
            else:
                formatted_lines.append(line)
        text = '\n'.join(formatted_lines)
        
        # Escape HTML to prevent XSS using Markup.escape() class method
        text = Markup.escape(text)
        text = str(text)
        
        # Convert newlines to <br>
        text = text.replace('\n', '<br/>')
        
        # Handle monospace (```text```) - must be done before other formatting
        # Match triple backticks with content (non-greedy)
        text = re.sub(r'```([^`]+)```', r'<code style="background-color: rgba(0,0,0,0.1); padding: 2px 4px; border-radius: 3px; font-family: monospace; font-size: 0.9em;">\1</code>', text)
        
        # Handle strikethrough (~text~) - match tilde with content
        text = re.sub(r'~([^~\n]+)~', r'<span style="text-decoration: line-through;">\1</span>', text)
        
        # Handle bold (*text*) - must be done before italic to avoid conflicts
        # Match asterisk with content (not newlines to avoid breaking blockquotes)
        text = re.sub(r'\*([^*\n]+)\*', r'<strong>\1</strong>', text)
        
        # Handle italic (_text_) - match underscore with content
        text = re.sub(r'_([^_\n]+)_', r'<em>\1</em>', text)
        
        return Markup(text)
    
    @api.depends('body', 'header_type', 'header_text', 'footer', 'button_ids', 'button_ids.button_type', 'button_ids.text')
    def _compute_template_preview_html(self):
        """Compute HTML preview of the template using QWeb template"""
        for record in self:
            try:
                # Get button information - ensure all required fields are present
                # Create a simple class that QWeb can access with dot notation
                class ButtonData:
                    def __init__(self, button_type, text, name, index):
                        self.type = button_type
                        self.text = text
                        self.name = name
                        self.index = index
                
                buttons = []
                for idx, button in enumerate(record.button_ids):
                    if button.button_type and button.text:
                        # Create ButtonData object that QWeb can access with dot notation
                        button_obj = ButtonData(
                            button_type=str(button.button_type) if button.button_type else 'QUICK_REPLY',
                            text=str(button.text) if button.text else '',
                            name=str(button.text) if button.text else '',  # For compatibility
                            index=idx,
                        )
                        buttons.append(button_obj)
                
                # Format body, header, and footer with WhatsApp styling
                formatted_body = self._format_whatsapp_text(record.body or '')
                formatted_header = self._format_whatsapp_text(record.header_text or '')
                formatted_footer = self._format_whatsapp_text(record.footer or '')
                
                # Use ir.ui.view to render the template
                preview = self.env['ir.ui.view']._render_template('comm_whatsapp.whatsapp_template_preview', {
                    'body': formatted_body,
                    'body_raw': record.body or '',  # Keep raw for fallback
                    'header_type': record.header_type or False,
                    'header_text': formatted_header,
                    'header_text_raw': record.header_text or '',  # Keep raw for fallback
                    'footer_text': formatted_footer,
                    'footer_text_raw': record.footer or '',  # Keep raw for fallback
                    'buttons': buttons,
                })
                record.template_preview_html = preview.decode('utf-8') if isinstance(preview, bytes) else preview
            except Exception as e:
                _logger.warning(f"Error rendering template preview: {e}", exc_info=True)
                record.template_preview_html = f'<div style="color: red;">Error rendering preview: {str(e)}</div>'

    def _resolve_meta_creds(self):
        """Return (access_token, business_account_id, source_label).
        Priority: context['force_account_id'] → self.account_id → the
        legacy system parameters."""
        forced = self.env.context.get('force_account_id')
        if forced:
            acc = self.env['comm.whatsapp.account'].sudo().browse(forced)
            if acc.exists():
                return (
                    acc.access_token or '',
                    acc.business_account_id or '',
                    f"account '{acc.name}'",
                )
        if self and self[:1].account_id:
            acc = self[:1].account_id
            return (
                acc.access_token or '',
                acc.business_account_id or '',
                f"account '{acc.name}'",
            )
        icp = self.env['ir.config_parameter'].sudo()
        return (
            icp.get_param('comm_whatsapp.access_token')
            or icp.get_param('comm_whatsapp.long_lived_token')
            or '',
            icp.get_param('comm_whatsapp.business_account_id') or '',
            'system parameters',
        )

    def action_submit_to_meta(self):
        """
        Submit template to Meta WhatsApp Business API for approval.

        Based on: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview
        """
        self.ensure_one()

        try:
            access_token, business_account_id, _src = self._resolve_meta_creds()
            
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
                        'message': 'Business Account ID not configured. Please ensure webhook has been received to set this automatically.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            if self.is_call_permission_request:
                if self.category not in ('UTILITY', 'MARKETING'):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': 'Call permission request templates must be '
                                       'categorized as Utility or Marketing.',
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
                if self.button_ids:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': 'Call permission request templates cannot '
                                       'also have buttons — Meta rejects the '
                                       'combination. Remove the buttons first.',
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
            
            # Body component. A body written with {{customer_name}}-style
            # named placeholders needs Meta's named parameter_format
            # (body_text_named_params); the older {{1}}, {{2}}.. numbered
            # style keeps using the positional body_text example.
            body_component = {
                'type': 'BODY',
                'text': self.body,
            }
            named_params = self._extract_named_params()
            if named_params:
                body_component['example'] = {
                    'body_text_named_params': [
                        {'param_name': p, 'example': f'Example {p}'}
                        for p in named_params
                    ]
                }
            else:
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

            # Call permission request component — mutually exclusive with
            # buttons (enforced above), so this is the only interactive
            # component when enabled.
            if self.is_call_permission_request:
                components.append({'type': 'CALL_PERMISSION_REQUEST'})

            # Button components (group all buttons into one BUTTONS component)
            if self.button_ids and not self.is_call_permission_request:
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
                    elif button.button_type == 'FLOW':
                        # Flow button - according to WhatsApp Flows API docs
                        flow_button = {
                            'type': 'FLOW',
                            'text': button.text,
                        }
                        
                        # Add flow identifier (flow_id, flow_name, or flow_json)
                        # Priority: flow_id > flow_name > flow_json
                        if button.flow_id and button.flow_id.flow_id_meta:
                            flow_button['flow_id'] = button.flow_id.flow_id_meta
                        elif button.flow_id and button.flow_id.name:
                            flow_button['flow_name'] = button.flow_id.name
                        elif button.flow_id and button.flow_id.flow_json:
                            # Use flow_json as string (must be escaped JSON)
                            flow_button['flow_json'] = button.flow_id.flow_json
                        else:
                            # Skip this button if no flow is configured
                            _logger.warning(f"Skipping FLOW button '{button.text}' - no flow configured")
                            continue
                        
                        # Add flow_action if specified (default is 'navigate')
                        if button.flow_action:
                            flow_button['flow_action'] = button.flow_action
                        
                        # Add navigate_screen if specified
                        if button.navigate_screen:
                            flow_button['navigate_screen'] = button.navigate_screen
                        elif button.flow_id and button.flow_id.first_page_id:
                            # Use first page ID from flow if available
                            flow_button['navigate_screen'] = button.flow_id.first_page_id
                        
                        buttons_list.append(flow_button)
                
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
            if named_params:
                payload['parameter_format'] = 'named'

            # API endpoint - Use business account ID, not phone number ID
            # According to Meta docs: POST /v18.0/{whatsapp-business-account-id}/message_templates
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/message_templates"
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

    def _extract_named_params(self):
        """Named {{param_name}} placeholders from the body, in the order
        they first appear — Meta's newer named parameter_format, as
        opposed to the numbered {{1}}, {{2}}.. style _extract_example_params
        handles. A body mixing both styles isn't valid on Meta's side;
        this only recognizes non-numeric names."""
        if not self.body:
            return []
        seen = []
        for m in re.finditer(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}', self.body):
            name = m.group(1)
            if name not in seen:
                seen.append(name)
        return seen

    def action_fetch_from_meta(self):
        """
        Fetch templates from Meta API and sync with local records.
        """
        try:
            access_token, business_account_id, cred_src = self._resolve_meta_creds()

            if not access_token or not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': (
                            f"Access token or Business Account ID missing from "
                            f"{cred_src}."
                        ),
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Fetch templates from Meta - Use business account ID
            # According to Meta docs: GET /v18.0/{whatsapp-business-account-id}/message_templates
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/message_templates"
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
                    
                    # Find or create template. Scope the lookup to the
                    # forced account (if any) so two WABAs can host their
                    # own copy of the same template name/language pair.
                    forced_account_id = self.env.context.get('force_account_id')
                    search_domain = [
                        ('name', '=', name),
                        ('language', '=', language),
                    ]
                    if forced_account_id:
                        search_domain.append(('account_id', '=', forced_account_id))
                    template = self.search(search_domain, limit=1)

                    vals = {
                        'template_id_meta': template_data.get('id'),
                        'status': status,
                        'quality_score': quality,
                        'category': template_data.get('category', 'UTILITY'),
                    }
                    if forced_account_id:
                        vals['account_id'] = forced_account_id
                    
                    # Extract components (for both new and existing templates)
                    components = template_data.get('components', [])
                    body_text = ''
                    footer_text = ''
                    header_type = False
                    header_text = ''
                    buttons_data = []
                    is_call_permission_request = False

                    for component in components:
                        if component.get('type') == 'BODY':
                            body_text = component.get('text', '')
                        elif component.get('type') == 'FOOTER':
                            footer_text = component.get('text', '')
                        elif (component.get('type') or '').upper() == 'CALL_PERMISSION_REQUEST':
                            # Meta echoes this back uppercase on fetch even
                            # though it's submitted lowercase — same as
                            # BODY/HEADER/FOOTER, just easy to miss since
                            # this component type is much newer than those.
                            is_call_permission_request = True
                        elif component.get('type') == 'HEADER':
                            header_format = component.get('format')
                            if header_format == 'TEXT':
                                header_type = 'TEXT'
                                header_text = component.get('text', '')
                            elif header_format in ('IMAGE', 'VIDEO', 'DOCUMENT'):
                                header_type = header_format
                        elif component.get('type') == 'BUTTONS':
                            # Extract buttons from BUTTONS component
                            buttons = component.get('buttons', [])
                            for idx, button in enumerate(buttons):
                                button_type = button.get('type')
                                button_text = button.get('text', '')
                                
                                # Extract button-specific data based on type
                                button_data = {
                                    'sequence': idx * 10,  # 0, 10, 20, etc.
                                    'button_type': button_type,
                                    'text': button_text,
                                }
                                
                                # Extract data based on button type
                                if button_type == 'URL':
                                    button_data['url'] = button.get('url', '')
                                elif button_type == 'PHONE_NUMBER':
                                    button_data['phone_number'] = button.get('phone_number', '')
                                elif button_type == 'FLOW':
                                    # For FLOW buttons, extract action data
                                    action = button.get('action', {})
                                    # Meta stores flow_id in the action
                                    flow_id_meta = action.get('flow_id') or action.get('flow_token')
                                    if flow_id_meta:
                                        # Try to find the flow in our system by Meta flow ID
                                        flow = self.env['whatsapp.flow'].search([
                                            ('flow_id_meta', '=', flow_id_meta)
                                        ], limit=1)
                                        if flow:
                                            button_data['flow_id'] = flow.id
                                    
                                    # Extract flow action type (default to 'navigate')
                                    button_data['flow_action'] = action.get('flow_action', 'navigate')
                                    
                                    # Extract navigate screen if present
                                    # Meta might store it as navigate_screen.screen.name or just navigate_screen
                                    navigate_screen = action.get('navigate_screen')
                                    if navigate_screen:
                                        if isinstance(navigate_screen, dict):
                                            screen = navigate_screen.get('screen', {})
                                            if isinstance(screen, dict):
                                                button_data['navigate_screen'] = screen.get('name', '')
                                            else:
                                                button_data['navigate_screen'] = str(screen)
                                        else:
                                            button_data['navigate_screen'] = str(navigate_screen)
                                    else:
                                        button_data['navigate_screen'] = ''
                                
                                buttons_data.append(button_data)
                    
                    if template:
                        # Update existing template
                        vals.update({
                            'body': body_text,
                            'footer': footer_text,
                            'header_type': header_type,
                            'header_text': header_text,
                            'is_call_permission_request': is_call_permission_request,
                        })
                        template.write(vals)
                        
                        # Update buttons - delete existing and recreate
                        template.button_ids.unlink()
                        for button_data in buttons_data:
                            # Try to find flow if it's a FLOW button
                            flow_id = False
                            if button_data.get('button_type') == 'FLOW':
                                # Try to find flow by Meta flow ID from the button action
                                flow_token = button_data.get('flow_action')  # This might be in the action
                                # Note: Meta stores flow_id in the action, but we need to match it
                                # For now, we'll leave flow_id empty and let user set it manually
                                pass
                            
                            button_vals = {
                                'template_id': template.id,
                                'sequence': button_data.get('sequence', 0),
                                'button_type': button_data.get('button_type', 'QUICK_REPLY'),
                                'text': button_data.get('text', ''),
                                'url': button_data.get('url', ''),
                                'phone_number': button_data.get('phone_number', ''),
                                'flow_action': button_data.get('flow_action') or 'navigate',
                                'navigate_screen': button_data.get('navigate_screen', ''),
                            }
                            if flow_id:
                                button_vals['flow_id'] = flow_id
                            self.env['whatsapp.template.button'].create(button_vals)
                        
                        updated_count += 1
                    else:
                        # Create new template
                        vals.update({
                            'name': name,
                            'language': language,
                            'body': body_text,
                            'footer': footer_text,
                            'header_type': header_type,
                            'header_text': header_text,
                            'is_call_permission_request': is_call_permission_request,
                        })
                        template = self.create(vals)
                        
                        # Create buttons
                        for button_data in buttons_data:
                            # Try to find flow if it's a FLOW button
                            flow_id = False
                            if button_data.get('button_type') == 'FLOW':
                                # Try to find flow by Meta flow ID from the button action
                                # Note: Meta stores flow_id in the action, but we need to match it
                                # For now, we'll leave flow_id empty and let user set it manually
                                pass
                            
                            button_vals = {
                                'template_id': template.id,
                                'sequence': button_data.get('sequence', 0),
                                'button_type': button_data.get('button_type', 'QUICK_REPLY'),
                                'text': button_data.get('text', ''),
                                'url': button_data.get('url', ''),
                                'phone_number': button_data.get('phone_number', ''),
                                'flow_action': button_data.get('flow_action') or 'navigate',
                                'navigate_screen': button_data.get('navigate_screen', ''),
                            }
                            if flow_id:
                                button_vals['flow_id'] = flow_id
                            self.env['whatsapp.template.button'].create(button_vals)
                        
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

    def _send_simple(self, to_number, variables=None):
        """Send this template to `to_number` — for system-triggered sends
        (e.g. the WhatsApp calling widget's "send a call permission
        request" prompt) that don't go through the interactive wizard.

        `variables` is an optional dict used to fill body placeholders:
        for a named-format body (see _extract_named_params), keys match
        each {{param_name}}; for the older numbered {{1}}, {{2}}.. style,
        every slot gets `variables['_default']` instead, since there's no
        per-placeholder name to key by. Any placeholder with no supplied
        value falls back to a generic word rather than failing the send
        outright. Templates with no body placeholders at all ignore
        `variables` and send as-is.

        Returns {'success': True} or {'success': False, 'error': <message>}.
        """
        self.ensure_one()
        if self.status != 'APPROVED':
            return {'success': False,
                    'error': f"Template '{self.name}' is not approved "
                             f"(status: {self.status})."}

        access_token, _biz_id, _src = self._resolve_meta_creds()
        phone_number_id = (
            self.account_id.phone_number_id if self.account_id
            else self.env['ir.config_parameter'].sudo().get_param(
                'comm_whatsapp.phone_number_id')
        )
        if not access_token or not phone_number_id:
            return {'success': False,
                    'error': "WhatsApp isn't configured (missing access "
                             "token or phone number)."}

        recipient = re.sub(r'[^0-9]', '', to_number or '')
        if not recipient:
            return {'success': False, 'error': "Missing recipient number."}

        template_payload = {
            'name': self.name,
            'language': {'code': self.language},
        }
        variables = variables or {}
        named_params = self._extract_named_params()
        if named_params:
            template_payload['components'] = [{
                'type': 'body',
                'parameters': [
                    {
                        'type': 'text',
                        'parameter_name': p,
                        'text': str(variables.get(p) or 'there'),
                    }
                    for p in named_params
                ],
            }]
        else:
            # Older {{1}}, {{2}}.. numbered placeholders still need their
            # slots filled at send time, or Meta rejects the send with a
            # parameter-count mismatch — there's just no per-placeholder
            # name to key variables by, so every slot gets the same
            # caller-supplied fallback (e.g. the recipient's display name).
            positional_count = len(re.findall(r'\{\{(\d+)\}\}', self.body or ''))
            if positional_count:
                fallback_value = str(variables.get('_default') or 'there')
                template_payload['components'] = [{
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': fallback_value}
                        for _ in range(positional_count)
                    ],
                }]

        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': recipient,
            'type': 'template',
            'template': template_payload,
        }
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            if r.ok:
                self.write({
                    'usage_count': self.usage_count + 1,
                    'last_used': fields.Datetime.now(),
                })
                return {'success': True}
            try:
                error_message = (r.json() or {}).get('error', {}).get('message', r.text)
            except Exception:
                error_message = r.text[:200] if r.text else f"HTTP {r.status_code}"
            _logger.error(
                "comm_whatsapp: template '%s' send failed (%s): %s",
                self.name, r.status_code, error_message,
            )
            return {'success': False, 'error': error_message}
        except Exception as e:
            _logger.error("comm_whatsapp: template '%s' send error: %s", self.name, e)
            return {'success': False, 'error': str(e)}


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
        ('FLOW', 'Flow'),
    ], string='Button Type', required=True, default='QUICK_REPLY')
    text = fields.Char(string='Button Text', required=True, size=25,
                     help='Button label (max 25 characters)')
    url = fields.Char(string='URL', help='URL for URL button type')
    phone_number = fields.Char(string='Phone Number', help='Phone number for PHONE_NUMBER button type')
    
    # Flow button fields
    flow_id = fields.Many2one('whatsapp.flow', string='Flow',
                             help='Flow to attach to this button (for FLOW button type)')
    flow_action = fields.Selection([
        ('navigate', 'Navigate'),
        ('data_exchange', 'Data Exchange'),
    ], string='Flow Action', default='navigate',
       help='Flow action type: navigate (default) or data_exchange')
    navigate_screen = fields.Char(string='Navigate Screen',
                                help='Screen ID to navigate to (optional, defaults to first entry screen)')

