# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import time

from odoo import api, fields, models


class CommVoipAccount(models.Model):
    _name = 'comm.voip.account'
    _description = 'VoIP Account / Provider Config'
    _order = 'sequence, id'
    _rec_name = 'name'

    name = fields.Char('Display Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean('Default Account')

    # What this account is used for — an app can run an agent softphone AND
    # an automation/API account side by side under the same voip channel.
    usage = fields.Selection([
        ('agent', 'Agent Softphone'),
        ('automation', 'Automation / API'),
        ('both', 'Both'),
    ], string='Usage', default='automation', required=True)

    provider = fields.Selection([
        # Cloud Voice APIs (REST + webhooks) — automation-friendly.
        ('infobip', 'Infobip Voice'),
        ('africas_talking', "Africa's Talking Voice"),
        ('twilio', 'Twilio'),
        # SIP / WebRTC softphone (agent-facing).
        ('sip', 'SIP Trunk / PBX'),
        ('axivox', 'Axivox (SIP/WebRTC)'),
        ('onsip', 'OnSIP (SIP/WebRTC)'),
        # Self-hosted media engine driven over ARI (progressive/predictive dialer
        # + agent WebRTC): SIP trunk to the PSTN, agents register over WSS.
        ('asterisk', 'Asterisk (ARI + SIP/WebRTC)'),
        ('other', 'Other'),
    ], string='Provider', default='other', required=True)

    # Asterisk REST Interface (ARI) — used when provider = asterisk. The dialer's
    # ARI bridge service authenticates here to originate / AMD / bridge calls.
    ari_base_url = fields.Char('ARI Base URL', help="e.g. http://asterisk:8088")
    ari_username = fields.Char('ARI Username')
    ari_password = fields.Char('ARI Password')
    ari_app = fields.Char('Stasis App', default='comm_dialer',
                          help="Name of the ARI Stasis application the bridge service runs.")
    trunk_name = fields.Char('SIP Trunk', help="PJSIP endpoint/trunk name for outbound PSTN calls (e.g. vox).")

    # TURN (coturn) — for agent WebRTC media relay behind NAT.
    turn_url = fields.Char('TURN URL',
                           help="e.g. turn:203.0.113.10:3478 — given to agent softphones for media relay.")
    turn_secret = fields.Char('TURN Secret',
                              help="coturn static-auth-secret; Odoo mints short-lived ICE credentials from it.")

    def get_ice_servers(self, ttl=3600):
        """ICE server config (STUN/TURN) for an agent's WebRTC softphone.

        Uses coturn's use-auth-secret (REST) scheme: the username is an expiry
        timestamp and the credential is base64(HMAC-SHA1(secret, username)), so
        Odoo never ships the long-lived TURN secret to the browser."""
        self.ensure_one()
        servers = []
        if self.turn_url and self.turn_secret:
            username = '%d:%s' % (int(time.time()) + ttl, self.env.user.login)
            digest = hmac.new(self.turn_secret.encode(), username.encode(),
                              hashlib.sha1).digest()
            servers.append({
                'urls': [self.turn_url],
                'username': username,
                'credential': base64.b64encode(digest).decode(),
            })
        return servers

    # Which providers are SIP/WebRTC (softphone) vs cloud-API (REST).
    is_sip = fields.Boolean(compute='_compute_is_sip')

    # Cloud-API providers (Infobip / Africa's Talking / Twilio / other HTTP).
    base_url = fields.Char('API Base URL')
    api_key = fields.Char('API Key / Auth Token')
    caller_id = fields.Char('Caller ID / From Number',
                            help="The number/ID shown to the person being called.")

    # SIP / WebRTC credentials (provider = sip / axivox / onsip).
    sip_domain = fields.Char('SIP Domain')
    sip_username = fields.Char('SIP Username')
    sip_password = fields.Char('SIP Password')
    sip_ws_url = fields.Char('WebSocket URL (WSS)',
                             help="Secure WebSocket the browser softphone connects to (WebRTC).")

    @api.depends('provider')
    def _compute_is_sip(self):
        for rec in self:
            rec.is_sip = rec.provider in ('sip', 'axivox', 'onsip', 'asterisk')

    webhook_hint = fields.Char(
        'Inbound Webhook', compute='_compute_webhook_hint',
        help="Point your provider's inbound-call webhook here (once the "
             "provider send/receive is wired).")
    call_count = fields.Integer('Calls', compute='_compute_call_count')

    def _compute_webhook_hint(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for rec in self:
            rec.webhook_hint = '%s/voip/inbound' % base if base else '/voip/inbound'

    def _compute_call_count(self):
        Call = self.env['comm.voip.call']
        for rec in self:
            rec.call_count = Call.search_count([('account_id', '=', rec.id)])

    @api.model
    def get_default(self):
        return self.search([('active', '=', True), ('is_default', '=', True)], limit=1) \
            or self.search([('active', '=', True)], limit=1)
