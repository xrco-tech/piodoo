# -*- coding: utf-8 -*-
"""SMS Account — one row per sender ID / provider account.

Replaces the single-row ir.config_parameter setup so an Odoo install can run
several SMS senders (different sender IDs, different providers) side by side.
Supported providers: Infobip, Africa's Talking, Connect Mobile.

A migration in 1.0.1 backfills a 'Default SMS' account from the existing
sms.use_infobip_api / infobip.* config keys so existing single-account
installs keep working without manual intervention.
"""

import secrets

from werkzeug.urls import url_join

from odoo import api, fields, models

PROVIDER_SELECTION = [
    ('infobip', 'Infobip'),
    ('africastalking', "Africa's Talking"),
    ('connect_mobile', 'Connect Mobile'),
]

# Callback paths per provider: (delivery reports, inbound MO). The MO routes
# live in comm_whatsapp_chatbot because they feed the chatbot runtime.
PROVIDER_WEBHOOK_PATHS = {
    'infobip': ('/sms/infobip/status', '/sms/infobip/inbound'),
    'africastalking': ('/sms/africastalking/status', '/sms/africastalking/inbound'),
    'connect_mobile': ('/sms/connectmobile/dlr', '/sms/connectmobile/inbound'),
}


def _new_webhook_token():
    return secrets.token_urlsafe(24)


class CommSmsAccount(models.Model):
    _name = 'comm.sms.account'
    _description = 'SMS Account'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char(string="Display Name", required=True, tracking=True,
                       help="Human label for this account (e.g. 'Marketing Sender').")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    provider = fields.Selection(PROVIDER_SELECTION, string="Provider", required=True,
                                default='infobip', tracking=True)

    sender_id = fields.Char(
        string="Sender ID / From Number", required=True, tracking=True, index='btree',
        help="The address messages are sent FROM and that inbound MO arrives addressed TO. "
             "Either a phone number in international format (e.g. +27693808740) or an "
             "alphanumeric sender ID (e.g. PIODOO).",
    )

    # Provider credentials. base_url + api_key are shared by all providers;
    # username + use_sandbox are Africa's Talking only.
    base_url = fields.Char(string="Base URL",
                           help="Provider API base URL. Infobip: your-instance.api.infobip.com. "
                                "Connect Mobile: leave empty for sms.connect-mobile.co.za. "
                                "Africa's Talking: leave empty.")
    api_key = fields.Char(string="API Key",
                          help="Bearer token / API key used on outbound API calls.")
    username = fields.Char(string="Username",
                           help="Africa's Talking app username ('sandbox' for the sandbox).")
    use_sandbox = fields.Boolean(string="Sandbox",
                                 help="Send through Africa's Talking's sandbox API instead of live.")
    retention_period = fields.Integer(string="Retention Period (days)", default=1)

    # Shared secret appended as ?token= to callback URLs. Infobip delivery
    # reports get it automatically (notifyUrl is set per message); for the
    # other callbacks, paste the URLs below into the provider's dashboard.
    webhook_token = fields.Char(string="Webhook Token", copy=False,
                                default=lambda self: _new_webhook_token(),
                                groups='base.group_system')
    dlr_webhook_url = fields.Char(string="Delivery Report URL", compute='_compute_webhook_urls',
                                  groups='base.group_system')
    inbound_webhook_url = fields.Char(string="Inbound SMS URL", compute='_compute_webhook_urls',
                                      groups='base.group_system')

    is_default = fields.Boolean(
        string="Default Account", default=False,
        help="If multiple accounts can match an inbound, the default wins.",
    )

    # Smart-button count of sms.sms records linked to this account.
    sms_count = fields.Integer(compute='_compute_sms_count')

    _sql_constraints = [
        ('sender_id_unique_per_provider',
         'UNIQUE(provider, sender_id)',
         "An SMS account with this provider + sender ID already exists."),
    ]

    @api.depends('provider', 'webhook_token')
    def _compute_webhook_urls(self):
        for rec in self:
            dlr_path, mo_path = PROVIDER_WEBHOOK_PATHS.get(rec.provider, (False, False))
            rec.dlr_webhook_url = rec._webhook_url(dlr_path) if dlr_path else False
            rec.inbound_webhook_url = rec._webhook_url(mo_path) if mo_path else False

    def _webhook_url(self, path):
        """Absolute https callback URL for `path`, carrying this account's token."""
        self.ensure_one()
        base_url = self.get_base_url()
        # Providers only call SSL-protected URLs
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        url = url_join(base_url, path)
        if self.sudo().webhook_token:
            url += f"?token={self.sudo().webhook_token}"
        return url

    def action_regenerate_webhook_token(self):
        for rec in self:
            rec.sudo().webhook_token = _new_webhook_token()

    @api.model
    def find_for_webhook_token(self, provider, token):
        """Account of `provider` whose webhook token is `token`, or empty."""
        if not token:
            return self.browse()
        return self.sudo().search(
            [('provider', '=', provider), ('webhook_token', '=', token), ('active', '=', True)],
            limit=1,
        )

    def _compute_sms_count(self):
        Sms = self.env['sms.sms']
        for rec in self:
            rec.sms_count = Sms.search_count([('account_id', '=', rec.id)])

    def action_view_sms(self):
        """Open the sms.sms list scoped to this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f"SMS — {self.name}",
            'res_model': 'sms.sms',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    @api.model
    def find_for_sender_id(self, sender_id):
        """Resolve an account by the inbound's `to` field. Returns an empty
        recordset when no match is found."""
        if not sender_id:
            return self.browse()
        return self.sudo().search(
            [('sender_id', '=', sender_id), ('active', '=', True)],
            limit=1,
        )

    @api.model
    def get_default(self):
        default = self.sudo().search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if default:
            return default
        return self.sudo().search([('active', '=', True)], order='sequence, id', limit=1)
