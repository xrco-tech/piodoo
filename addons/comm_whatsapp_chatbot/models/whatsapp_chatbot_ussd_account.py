# -*- coding: utf-8 -*-
"""USSD Account — one row per service code / gateway pairing.

USSD is interesting in that the inbound is the source of truth: we route by
the dialled `serviceCode`. Credentials are usually unnecessary on the
inbound path (the gateway already authenticated the caller); outbound
sessions (e.g. push USSD) can use api_key when needed.
"""

from odoo import api, fields, models


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

    is_default = fields.Boolean(
        string="Default Account", default=False,
        help="If multiple accounts can match an inbound, the default wins.",
    )

    _sql_constraints = [
        ('service_code_unique',
         'UNIQUE(service_code)',
         "A USSD account already exists for this service code."),
    ]

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
