# -*- coding: utf-8 -*-
"""WhatsApp Flow Component.

A single visible element on a screen. One model covers all component types
via the `component_type` Selection; per-type fields are conditionally visible
in the form view (same pattern as whatsapp.chatbot.step uses for step types).

Reference: https://developers.facebook.com/docs/whatsapp/flows/reference/components
"""

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


# Components carrying user input have a 'name' attribute that becomes a form
# field at runtime ({form.<name>} in Flow JSON). Must be lowercase snake_case.
# Meta's Flow JSON spec accepts any letter, digit, or underscore in a
# component's `name`, and does not require snake_case — real Meta-authored
# flows commonly ship names like `Name`, `Order_number`, or `Choose_a_topic`.
# We accept the same set so Sync from Meta doesn't reject valid remote flows.
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# Set of component types that are user-input-bearing (need a name + label).
INPUT_TYPES = {
    'TextInput', 'TextArea', 'Dropdown', 'RadioButtonsGroup', 'CheckboxGroup',
    'DatePicker', 'OptIn', 'PhotoPicker', 'DocumentPicker',
}

# Set of component types that carry an on-click-action (navigate/complete/etc).
ACTION_TYPES = {'Footer', 'EmbeddedLink', 'OptIn'}

# Set of component types that need an `options` list (Dropdown / Radio / Check).
CHOICE_TYPES = {'Dropdown', 'RadioButtonsGroup', 'CheckboxGroup'}


class WhatsAppFlowComponent(models.Model):
    _name = 'whatsapp.flow.component'
    _description = 'WhatsApp Flow Component'
    _order = 'screen_id, sequence, id'

    screen_id = fields.Many2one(
        'whatsapp.flow.screen', string='Screen', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    # Convenience back-pointer for the form view / domain filters.
    flow_id = fields.Many2one(
        'whatsapp.flow', related='screen_id.flow_id', string='Flow', store=True,
    )

    component_type = fields.Selection([
        # Display
        ('TextHeading',       'Text Heading'),
        ('TextSubheading',    'Text Subheading'),
        ('TextBody',          'Text Body'),
        ('TextCaption',       'Text Caption'),
        ('RichText',          'Rich Text (Markdown)'),
        ('Image',             'Image'),
        # Inputs
        ('TextInput',         'Text Input'),
        ('TextArea',          'Text Area'),
        ('Dropdown',          'Dropdown'),
        ('RadioButtonsGroup', 'Radio Buttons'),
        ('CheckboxGroup',     'Checkboxes'),
        ('DatePicker',        'Date Picker'),
        ('OptIn',             'Opt-In Checkbox'),
        ('PhotoPicker',       'Photo Picker'),
        ('DocumentPicker',    'Document Picker'),
        # Navigation / containers
        ('EmbeddedLink',      'Embedded Link'),
        ('Footer',            'Footer (CTA Button)'),
    ], string='Component Type', required=True, default='TextBody')

    # ── Universal display fields ─────────────────────────────────────────
    name = fields.Char(
        string='Field Name',
        help="Lowercase snake_case identifier used to reference this field "
             "in the Flow JSON (e.g. ${form.first_name}). Required on input "
             "and action-bearing components.",
    )
    label = fields.Char(
        string='Label',
        help="Visible text. For input components this is shown above the field; "
             "for Footer it's the button label; for text display components it "
             "becomes the rendered text.",
    )
    text = fields.Text(
        string='Text',
        help="Free-form text shown on the screen. Used by TextHeading / "
             "TextSubheading / TextBody / TextCaption / RichText. Supports "
             "{data.foo} and {form.foo} substitution at runtime.",
    )
    helper_text = fields.Char(
        string='Helper Text',
        help="Hint shown beneath the input field.",
    )
    required = fields.Boolean(
        string='Required',
        help="If True, the user can't proceed without filling this field.",
    )

    # ── Input-specific fields ────────────────────────────────────────────
    input_type = fields.Selection([
        ('text',     'Text'),
        ('number',   'Number'),
        ('email',    'Email'),
        ('password', 'Password'),
        ('passcode', 'Passcode'),
        ('phone',    'Phone Number'),
    ], string='Input Type',
       help="The expected data type for TextInput components.")
    min_chars = fields.Integer(string='Min Chars')
    max_chars = fields.Integer(string='Max Chars',
        help="Maximum number of characters the user can enter. Use 0 for no limit.")
    init_value = fields.Char(
        string='Initial Value',
        help="Pre-filled value when the screen renders.",
    )

    # CheckboxGroup-specific
    min_selected = fields.Integer(string='Min Selected')
    max_selected = fields.Integer(string='Max Selected',
        help="0 = no limit.")

    # DatePicker-specific
    min_date = fields.Char(
        string='Min Date',
        help="Earliest selectable date in YYYY-MM-DD format. Optional.",
    )
    max_date = fields.Char(
        string='Max Date',
        help="Latest selectable date in YYYY-MM-DD format. Optional.",
    )

    # ── Image-specific ──────────────────────────────────────────────────
    image_src = fields.Char(
        string='Image Source',
        help="Image URL or base64-encoded data. Required for Image components.",
    )
    image_alt = fields.Char(string='Alt Text')
    image_height = fields.Integer(string='Image Height', default=200)
    image_scale = fields.Selection([
        ('contain', 'Contain'),
        ('cover',   'Cover'),
    ], string='Image Scale', default='contain')

    # ── Media picker fields (PhotoPicker / DocumentPicker) ──────────────
    photo_source = fields.Selection([
        ('camera',         'Camera Only'),
        ('photo_gallery',  'Gallery Only'),
        ('camera_gallery', 'Camera + Gallery'),
    ], string='Photo Source', default='camera_gallery')
    min_uploaded = fields.Integer(string='Min Files', default=1)
    max_uploaded = fields.Integer(string='Max Files', default=1)
    max_file_size_kb = fields.Integer(string='Max File Size (KB)',
        help="Maximum size in kilobytes (e.g. 1024 for 1 MB). 0 = no limit.")

    # ── Action fields (Footer, EmbeddedLink, OptIn) ─────────────────────
    action_type = fields.Selection([
        ('navigate',      'Navigate to another screen'),
        ('complete',      'Complete the flow (terminal CTA)'),
        ('open_url',      'Open a URL outside WhatsApp'),
        ('data_exchange', 'Call data_exchange endpoint'),
    ], string='Action Type',
       help="What happens when the user taps this component.")
    target_screen_id = fields.Many2one(
        'whatsapp.flow.screen', string='Navigate to',
        domain="[('flow_id', '=', flow_id)]",
        help="When action_type=navigate, the destination screen.",
    )
    open_url = fields.Char(
        string='Open URL',
        help="When action_type=open_url, the destination URL.",
    )
    payload_keys = fields.Char(
        string='Payload Keys (CSV)',
        help="Comma-separated list of form field names to forward in the "
             "action's payload. Leave blank to forward all form fields.",
    )

    # ── Options for choice components ───────────────────────────────────
    option_ids = fields.One2many(
        'whatsapp.flow.component.option', 'component_id', string='Options',
    )

    # ── Computed helpers used by views to gate field visibility ──────────
    is_input  = fields.Boolean(compute='_compute_role_flags')
    is_action = fields.Boolean(compute='_compute_role_flags')
    is_choice = fields.Boolean(compute='_compute_role_flags')

    @api.depends('component_type')
    def _compute_role_flags(self):
        for rec in self:
            rec.is_input  = rec.component_type in INPUT_TYPES
            rec.is_action = rec.component_type in ACTION_TYPES
            rec.is_choice = rec.component_type in CHOICE_TYPES

    # ── JSON rendering ──────────────────────────────────────────────────

    def _render_flow_json(self):
        """Return the component's representation in the Flow JSON schema, or
        None if it should be skipped (e.g. blank text component)."""
        self.ensure_one()
        t = self.component_type
        node = {"type": t}

        # Display components
        if t in ('TextHeading', 'TextSubheading', 'TextBody', 'TextCaption', 'RichText'):
            content = self.text or self.label or ''
            if not content.strip():
                return None
            node["text"] = content
            return node

        if t == 'Image':
            node["src"] = self.image_src or ''
            if self.image_alt:
                node["alt-text"] = self.image_alt
            if self.image_height:
                node["height"] = self.image_height
            if self.image_scale:
                node["scale-type"] = self.image_scale
            return node

        if t == 'EmbeddedLink':
            node["text"] = self.label or self.text or 'Link'
            node["on-click-action"] = self._render_action()
            return node

        if t == 'Footer':
            node["label"] = self.label or 'Continue'
            node["on-click-action"] = self._render_action()
            return node

        # Input components
        if self.name:
            node["name"] = self.name
        if self.label:
            node["label"] = self.label
        if self.required:
            node["required"] = True
        if self.helper_text:
            node["helper-text"] = self.helper_text
        if self.init_value:
            node["init-value"] = self.init_value

        if t == 'TextInput':
            if self.input_type:
                node["input-type"] = self.input_type
            if self.min_chars:
                node["min-chars"] = self.min_chars
            if self.max_chars:
                node["max-chars"] = self.max_chars
            return node

        if t == 'TextArea':
            if self.max_chars:
                node["max-length"] = self.max_chars
            return node

        if t == 'Dropdown' or t == 'RadioButtonsGroup' or t == 'CheckboxGroup':
            node["data-source"] = [
                opt._render_option()
                for opt in self.option_ids.sorted(key=lambda o: (o.sequence, o.id))
                if opt.enabled
            ]
            if t == 'CheckboxGroup':
                if self.min_selected:
                    node["min-selected-items"] = self.min_selected
                if self.max_selected:
                    node["max-selected-items"] = self.max_selected
            return node

        if t == 'DatePicker':
            if self.min_date:
                node["min-date"] = self.min_date
            if self.max_date:
                node["max-date"] = self.max_date
            return node

        if t == 'OptIn':
            node["on-click-action"] = self._render_action()
            return node

        if t == 'PhotoPicker':
            node["photo-source"] = self.photo_source or 'camera_gallery'
            if self.min_uploaded:
                node["min-uploaded-photos"] = self.min_uploaded
            if self.max_uploaded:
                node["max-uploaded-photos"] = self.max_uploaded
            if self.max_file_size_kb:
                node["max-file-size-kb"] = self.max_file_size_kb
            return node

        if t == 'DocumentPicker':
            if self.min_uploaded:
                node["min-uploaded-documents"] = self.min_uploaded
            if self.max_uploaded:
                node["max-uploaded-documents"] = self.max_uploaded
            if self.max_file_size_kb:
                node["max-file-size-kb"] = self.max_file_size_kb
            return node

        return node

    def _render_action(self):
        """Return the on-click-action dict for action-bearing components."""
        self.ensure_one()
        if not self.action_type:
            return {"name": "complete"}
        if self.action_type == 'navigate':
            payload = self._render_payload()
            action = {
                "name": "navigate",
                "next": {
                    "type": "screen",
                    "name": self.target_screen_id.screen_id if self.target_screen_id else '',
                },
            }
            if payload:
                action["payload"] = payload
            return action
        if self.action_type == 'complete':
            payload = self._render_payload()
            action = {"name": "complete"}
            if payload:
                action["payload"] = payload
            return action
        if self.action_type == 'open_url':
            return {"name": "open_url", "url": self.open_url or ''}
        if self.action_type == 'data_exchange':
            payload = self._render_payload()
            action = {"name": "data_exchange"}
            if payload:
                action["payload"] = payload
            return action
        return {"name": "complete"}

    def _render_payload(self):
        """Build the action payload dict — maps form fields the agent
        wants forwarded to the action."""
        self.ensure_one()
        keys = (self.payload_keys or '').strip()
        if not keys:
            # Default: forward every input field on the same screen.
            input_names = [
                c.name for c in self.screen_id.component_ids
                if c.is_input and c.name
            ]
        else:
            input_names = [k.strip() for k in keys.split(',') if k.strip()]
        return {k: "${form." + k + "}" for k in input_names}

    @api.constrains('name', 'component_type')
    def _check_name(self):
        for rec in self:
            if rec.component_type in INPUT_TYPES or rec.component_type in ACTION_TYPES:
                if not rec.name:
                    continue  # the validator method will surface the error in the UI
                if not NAME_RE.match(rec.name):
                    raise ValidationError(
                        f"Component name '{rec.name}' must contain only "
                        "letters, digits and underscores, and must not start "
                        "with a digit."
                    )


class WhatsAppFlowComponentOption(models.Model):
    _name = 'whatsapp.flow.component.option'
    _description = 'WhatsApp Flow Component Option'
    _order = 'component_id, sequence, id'

    component_id = fields.Many2one(
        'whatsapp.flow.component', string='Component',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)

    option_id = fields.Char(
        string='Value', required=True,
        help="The value returned when the user picks this option. Lowercase "
             "snake_case is recommended (e.g. 'small', 'medium', 'large').",
    )
    title = fields.Char(
        string='Title', required=True,
        help="The visible label shown to the user.",
    )
    description = fields.Char(
        string='Description',
        help="Optional secondary label shown beneath the title.",
    )
    enabled = fields.Boolean(string='Enabled', default=True)

    _sql_constraints = [
        ('option_id_unique_per_component',
         'UNIQUE(component_id, option_id)',
         "Option values must be unique within a component."),
    ]

    def _render_option(self):
        """Serialise into the data-source dict the Flow JSON expects."""
        self.ensure_one()
        out = {"id": self.option_id, "title": self.title}
        if self.description:
            out["description"] = self.description
        if not self.enabled:
            out["enabled"] = False
        return out
