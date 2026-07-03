# -*- coding: utf-8 -*-
"""WhatsApp Business Account — one row per registered WABA phone number.

Multi-tenant credential store: replaces the single global ir.config_parameter
config so an Odoo install can run several WABA numbers side by side. Each
account holds everything needed to send + verify inbound for one number:

    phone_number          — what humans recognise, e.g. +27693808740
    phone_number_id       — Meta's internal ID needed for the Graph API call
    business_account_id   — WABA the number lives under
    access_token          — bearer token for /messages
    app_secret            — used to verify webhook signatures
    webhook_verify_token  — challenge response for the verification GET

A migration in 18.0.1.0.32 promotes the existing global config keys into a
"Default WhatsApp" account so existing installs keep working without manual
intervention.
"""

import logging
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppAccount(models.Model):
    _name = 'comm.whatsapp.account'
    _description = 'WhatsApp Business Account'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char(string="Display Name", required=True, tracking=True,
                       help="Human label for this account (e.g. 'Support Line').")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # Humans pick by phone number; the API needs phone_number_id.
    phone_number = fields.Char(
        string="Phone Number", required=True, tracking=True,
        help="The WABA-registered phone number in international format, e.g. +27693808740.",
    )
    phone_number_id = fields.Char(
        string="Phone Number ID", required=True, tracking=True, index='btree',
        help="Meta's internal phone_number_id used in the Graph API path. "
             "Found in your WhatsApp Business Manager next to the phone number.",
    )
    business_account_id = fields.Char(
        string="Business Account ID", tracking=True,
        help="The WABA ID this number lives under.",
    )

    # Credentials
    access_token = fields.Char(
        string="Access Token", tracking=False,
        help="Bearer token sent on every /messages request.",
    )
    app_secret = fields.Char(
        string="App Secret", tracking=False,
        help="Used to verify the X-Hub-Signature header on inbound webhooks.",
    )
    webhook_verify_token = fields.Char(
        string="Webhook Verify Token", tracking=False,
        help="Token that must match the challenge during webhook URL verification.",
    )

    is_default = fields.Boolean(
        string="Default Account", default=False,
        help="If multiple accounts can match an inbound, the default wins.",
    )

    # Populated by action_refresh_from_meta — the display name Meta
    # associates with this number (business name, e.g. "PIODOO Support").
    verified_name = fields.Char(
        string="Verified Name", readonly=True,
        help="Business name registered with Meta for this number. Populated "
             "by 'Refresh from Meta'.",
    )
    quality_rating = fields.Selection([
        ('GREEN',  'High'),
        ('YELLOW', 'Medium'),
        ('RED',    'Low'),
    ], string="Quality Rating", readonly=True)
    last_verified_at = fields.Datetime(
        string="Last Verified", readonly=True,
        help="When the phone number was last refreshed from Meta.",
    )

    # Smart-button counts.
    flow_count = fields.Integer(compute='_compute_flow_count')
    template_count = fields.Integer(compute='_compute_template_count')
    message_count = fields.Integer(compute='_compute_message_count')

    _sql_constraints = [
        ('phone_number_id_unique',
         'UNIQUE(phone_number_id)',
         "A WhatsApp account with this phone_number_id already exists."),
    ]

    def _compute_flow_count(self):
        Flow = self.env['whatsapp.flow']
        for rec in self:
            rec.flow_count = Flow.search_count([('account_id', '=', rec.id)])

    def _compute_template_count(self):
        Template = self.env['whatsapp.template']
        for rec in self:
            rec.template_count = Template.search_count(
                [('account_id', '=', rec.id)]
            )

    def _compute_message_count(self):
        Message = self.env['whatsapp.message']
        for rec in self:
            rec.message_count = Message.search_count(
                [('account_id', '=', rec.id)]
            )

    # ── Sync actions (invoked from the account form header) ───────────
    # Each pushes force_account_id into context so the target model's
    # _resolve_meta_creds() picks up this account's WABA credentials.

    def action_refresh_from_meta(self):
        """Look up this account's phone_number_id on Meta's Graph API and
        write back display_phone_number, verified_name, and quality_rating.
        Also usable as a sanity check that the access token still works."""
        self.ensure_one()
        if not self.access_token or not self.phone_number_id:
            raise UserError(
                "This account needs both an access_token and a "
                "phone_number_id before it can be refreshed from Meta."
            )
        url = (
            f"https://graph.facebook.com/v18.0/{self.phone_number_id}"
            "?fields=display_phone_number,verified_name,quality_rating"
        )
        headers = {'Authorization': f'Bearer {self.access_token}'}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.exceptions.RequestException as e:
            raise UserError(f"Network error talking to Meta: {e}")

        if resp.status_code != 200:
            err = (resp.json() or {}).get('error', {}) if resp.text else {}
            msg = err.get('message') or resp.text or f"HTTP {resp.status_code}"
            raise UserError(f"Meta rejected the lookup: {msg}")

        data = resp.json() or {}
        vals = {}
        if data.get('display_phone_number'):
            vals['phone_number'] = data['display_phone_number']
        if data.get('verified_name'):
            vals['verified_name'] = data['verified_name']
        raw_rating = (data.get('quality_rating') or '').upper()
        if raw_rating in ('GREEN', 'YELLOW', 'RED'):
            vals['quality_rating'] = raw_rating
        vals['last_verified_at'] = fields.Datetime.now()
        self.write(vals)
        _logger.info(
            "Refreshed WABA account #%s from Meta: %s", self.id, vals)

        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'Refreshed',
                'message': (
                    f"Phone: {vals.get('phone_number', self.phone_number)}\n"
                    f"Name:  {vals.get('verified_name', self.verified_name or '(none)')}"
                ),
                'type':    'success',
                'sticky':  False,
            },
        }

    def _require_creds(self):
        self.ensure_one()
        if not self.access_token or not self.business_account_id:
            from odoo.exceptions import UserError
            raise UserError(
                "This account is missing an Access Token or Business "
                "Account ID — set them on the Credentials tab first."
            )

    def action_sync_flows(self):
        self._require_creds()
        return self.env['whatsapp.flow'].with_context(
            force_account_id=self.id
        ).action_fetch_from_meta()

    def action_view_flows(self):
        """Open the Flows list filtered to this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f"Flows — {self.name}",
            'res_model': 'whatsapp.flow',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_sync_templates(self):
        self._require_creds()
        return self.env['whatsapp.template'].with_context(
            force_account_id=self.id
        ).action_fetch_from_meta()

    def action_view_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f"Messages — {self.name}",
            'res_model': 'whatsapp.message',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
        }

    def action_view_templates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f"Templates — {self.name}",
            'res_model': 'whatsapp.template',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    @api.model
    def find_for_phone_number_id(self, phone_number_id):
        """Resolve an account by inbound phone_number_id. Returns an empty
        recordset when no match is found (caller decides fallback)."""
        if not phone_number_id:
            return self.browse()
        return self.sudo().search(
            [('phone_number_id', '=', phone_number_id), ('active', '=', True)],
            limit=1,
        )

    @api.model
    def get_default(self):
        """The single account a caller should fall back on when no specific
        account is configured (preserves single-account installs)."""
        default = self.sudo().search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if default:
            return default
        # No explicit default → use the first active account.
        return self.sudo().search([('active', '=', True)], order='sequence, id', limit=1)
