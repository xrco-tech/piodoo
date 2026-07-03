# -*- coding: utf-8 -*-
"""SMS Account — one row per sender ID / provider account.

Replaces the single-row ir.config_parameter setup so an Odoo install can run
several SMS senders (different sender IDs, different providers in future)
side by side.

A migration in 1.0.1 backfills a 'Default SMS' account from the existing
sms.use_infobip_api / infobip.* config keys so existing single-account
installs keep working without manual intervention.
"""

from odoo import api, fields, models


class CommSmsAccount(models.Model):
    _name = 'comm.sms.account'
    _description = 'SMS Account'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char(string="Display Name", required=True, tracking=True,
                       help="Human label for this account (e.g. 'Marketing Sender').")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    provider = fields.Selection([
        ('infobip', 'Infobip'),
    ], string="Provider", required=True, default='infobip', tracking=True)

    sender_id = fields.Char(
        string="Sender ID / From Number", required=True, tracking=True, index='btree',
        help="The address messages are sent FROM and that inbound MO arrives addressed TO. "
             "Either a phone number in international format (e.g. +27693808740) or an "
             "alphanumeric sender ID (e.g. PIODOO).",
    )

    # Infobip credentials (other providers slot in here when needed).
    base_url = fields.Char(string="Base URL",
                           help="Provider API base URL, e.g. https://your-instance.api.infobip.com")
    api_key = fields.Char(string="API Key",
                          help="Bearer token / API key used on outbound API calls.")
    retention_period = fields.Integer(string="Retention Period (days)", default=1)

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
