# -*- coding: utf-8 -*-
"""USSD Account — one row per service code / gateway pairing.

USSD is interesting in that the inbound is the source of truth: we route by
the dialled `serviceCode`. Credentials are usually unnecessary on the
inbound path (the gateway already authenticated the caller); outbound
sessions (e.g. push USSD) can use api_key when needed.

Connect Mobile is the exception: its callback carries no service code we can
trust, so each account gets its own callback URL with a secret ?token= and
the token identifies the account.
"""

import secrets

from werkzeug.urls import url_join

from odoo import api, fields, models

# Providers whose callback is authenticated by the account's webhook token
PROVIDER_CALLBACK_PATHS = {
    'connect_mobile': '/ussd/connectmobile',
}


def _new_webhook_token():
    return secrets.token_urlsafe(24)


class CommUssdAccount(models.Model):
    _name = 'comm.ussd.account'
    _description = 'USSD Account'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char(string="Display Name", required=True, tracking=True,
                       help="Human label (e.g. 'Customer Service Code').")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    provider = fields.Selection([
        ('generic', 'Generic'),
        ('africastalking', "Africa's Talking"),
        ('connect_mobile', 'Connect Mobile'),
    ], string="Provider", default='generic', required=True, tracking=True)

    service_code = fields.Char(
        string="Service Code", required=True, tracking=True, index='btree',
        help="The dialled USSD code, e.g. *123# or *384*123#. "
             "Inbound is routed here when the gateway's serviceCode field matches.",
    )

    # Optional credentials for push-USSD or rate-limit-friendly verification.
    api_key = fields.Char(string="API Key",
                          help="Gateway API key, if outbound or verification is required.")
    base_url = fields.Char(string="Base URL",
                           help="Provider base URL for push-USSD or callbacks.")

    webhook_token = fields.Char(string="Webhook Token", copy=False,
                                default=lambda self: _new_webhook_token(),
                                groups='base.group_system')
    callback_url = fields.Char(string="Callback URL", compute='_compute_callback_url',
                               groups='base.group_system',
                               help="Give this URL to the provider as the USSD application endpoint.")

    is_default = fields.Boolean(
        string="Default Account", default=False,
        help="If multiple accounts can match an inbound, the default wins.",
    )

    _sql_constraints = [
        ('service_code_unique',
         'UNIQUE(service_code)',
         "A USSD account already exists for this service code."),
    ]

    @api.depends('provider', 'webhook_token')
    def _compute_callback_url(self):
        for rec in self:
            path = PROVIDER_CALLBACK_PATHS.get(rec.provider)
            if not path:
                rec.callback_url = False
                continue
            base_url = rec.get_base_url()
            # Providers only call SSL-protected URLs
            if base_url.startswith('http://'):
                base_url = base_url.replace('http://', 'https://', 1)
            rec.callback_url = f"{url_join(base_url, path)}?token={rec.sudo().webhook_token or ''}"

    def action_regenerate_webhook_token(self):
        for rec in self:
            rec.sudo().webhook_token = _new_webhook_token()

    @api.model
    def find_for_webhook_token(self, provider, token):
        """Active account of `provider` whose webhook token is `token`, or empty."""
        if not token:
            return self.browse()
        return self.sudo().search(
            [('provider', '=', provider), ('webhook_token', '=', token), ('active', '=', True)],
            limit=1,
        )

    @api.model
    def find_for_service_code(self, service_code):
        if not service_code:
            return self.browse()
        return self.sudo().search(
            [('service_code', '=', service_code), ('active', '=', True)],
            limit=1,
        )

    @api.model
    def get_default(self):
        default = self.sudo().search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if default:
            return default
        return self.sudo().search([('active', '=', True)], order='sequence, id', limit=1)
