# -*- coding: utf-8 -*-
"""USSD Account — one row per service code / gateway pairing.

USSD is interesting in that the inbound is the source of truth: we route by
the dialled `serviceCode`. Credentials are usually unnecessary on the
inbound path (the gateway already authenticated the caller); outbound
sessions (e.g. push USSD) can use api_key when needed.
"""

import ipaddress
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    ], string="Provider", default='generic', required=True, tracking=True,
        help="Africa's Talking and Generic codes are answered on /ussd/inbound; "
             "Connect Mobile codes on /ussd/connectmobile.")

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

    allowed_ips = fields.Text(
        string="Allowed Callers", tracking=True,
        help="Internet addresses the gateway calls us from, one per line: a single "
             "address (196.201.214.1) or a range (196.201.214.0/24). Requests for this "
             "code from anywhere else are refused. Leave empty to accept any caller.",
    )

    is_default = fields.Boolean(
        string="Default Account", default=False,
        help="If multiple accounts can match an inbound, the default wins.",
    )

    _sql_constraints = [
        ('service_code_unique',
         'UNIQUE(service_code)',
         "A USSD account already exists for this service code."),
    ]

    def _allowed_networks(self):
        self.ensure_one()
        entries = [e for e in re.split(r"[\s,;]+", self.allowed_ips or "") if e]
        return [ipaddress.ip_network(e, strict=False) for e in entries]

    @api.constrains('allowed_ips')
    def _check_allowed_ips(self):
        for account in self:
            try:
                account._allowed_networks()
            except ValueError as e:
                raise ValidationError(_(
                    "Allowed Callers on %(name)s has an entry that is not an address or a range: %(error)s",
                    name=account.name, error=e))

    def caller_allowed(self, ip):
        """Whether a gateway request from `ip` may use this code. No list
        means anyone; a list means only those addresses."""
        self.ensure_one()
        networks = self._allowed_networks()
        if not networks:
            return True
        try:
            address = ipaddress.ip_address((ip or "").strip())
        except ValueError:
            return False
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        return any(address in network for network in networks)

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


class CommUssdGatewaySession(models.Model):
    """What we must remember about a live session for a gateway that tells us
    less than Africa's Talking does: Connect Mobile sends only the latest
    entry and may not repeat the dialled code, and its session number can
    come round again."""
    _name = 'comm.ussd.gateway.session'
    _description = 'USSD Gateway Session'

    provider = fields.Char(required=True, index=True)
    key = fields.Char(required=True, index=True, help="The gateway's own session number and the caller.")
    service_code = fields.Char(required=True)
    network = fields.Char(help="The caller's mobile network, as the gateway names it.")
    breadcrumb = fields.Char(default='', help="Everything typed so far, joined by *.")
    turns = fields.Integer(default=0)
    session_id = fields.Char(compute='_compute_session_id',
                             help="The session id our flows see: never repeats, unlike the gateway's.")

    def _compute_session_id(self):
        for held in self:
            held.session_id = '%s-%s-%s' % (held.provider, held.key, held.id)

    @api.autovacuum
    def _gc_stale(self):
        """Sessions the gateway never told us had ended."""
        self.search([('create_date', '<', fields.Datetime.subtract(fields.Datetime.now(), days=1))]).unlink()
