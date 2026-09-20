# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import logging
import time

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def cloudflare_ice_servers(env, ttl=86400):
    """Short-lived ICE servers from Cloudflare Realtime TURN (managed), or None.

    Cloudflare mints the credentials server-side from a secret TURN token, so the
    long-lived token never reaches the browser. Config params (shared by the
    softphone and the WhatsApp-monitor relay):
      comm.turn.cf_key_id     — the TURN key id
      comm.turn.cf_api_token  — the TURN key's API token (secret)
    Returns a list of iceServer dicts, or None when unconfigured / on error so
    the caller can fall back to coturn."""
    ICP = env['ir.config_parameter'].sudo()
    key_id = ICP.get_param('comm.turn.cf_key_id')
    token = ICP.get_param('comm.turn.cf_api_token')
    if not (key_id and token):
        return None
    try:
        resp = requests.post(
            'https://rtc.live.cloudflare.com/v1/turn/keys/%s/credentials/generate-ice-servers' % key_id,
            headers={'Authorization': 'Bearer %s' % token},
            json={'ttl': int(ttl)}, timeout=8)
        resp.raise_for_status()
        ice = resp.json().get('iceServers')
        if isinstance(ice, dict):   # API returns a single object; consumers want a list
            ice = [ice]
        return _trim_ice_servers(ICP, ice) or None
    except Exception as e:
        _logger.warning('Cloudflare TURN credential fetch failed: %s', e)
        return None


def _trim_ice_servers(ICP, ice):
    """Drop ICE servers that stall the browser's ICE gathering on this network.

    JsSIP is non-trickle: it only sends the SIP answer (200 OK) once ICE
    gathering COMPLETES. Cloudflare's stock list includes stun.cloudflare.com
    plus four TCP/TLS TURN variants; stun.cloudflare.com is unreachable from
    this site (Asterisk's own STUN requests to it time out), so the browser sat
    in 'gathering' forever, the 200 was never sent and every inbound call died
    on the 30s Dial timeout. Keep only transports that gather fast here.

      comm.turn.drop_stun  — '0' to keep the plain STUN entry (default: drop)
      comm.turn.url_filter — substrings to keep, comma-separated
                             (default 'transport=udp,:443')
    """
    if not ice:
        return ice
    drop_stun = (ICP.get_param('comm.turn.drop_stun') or '1') != '0'
    # NB: Odoo's get_param returns False (not None) for a missing key, so take
    # the default via get_param's own default and coerce to a string.
    raw_filter = ICP.get_param('comm.turn.url_filter', 'transport=udp,:443') or ''
    wanted = [f.strip() for f in raw_filter.split(',') if f.strip()]
    out = []
    for srv in ice:
        urls = srv.get('urls') or []
        if isinstance(urls, str):
            urls = [urls]
        if not srv.get('username'):
            if drop_stun:
                continue  # plain STUN entry — unreachable here, stalls gathering
        elif wanted:
            kept = [u for u in urls if any(w in u for w in wanted)]
            urls = kept or urls  # never filter a TURN entry down to nothing
        out.append(dict(srv, urls=urls))
    return out


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

        Prefers Cloudflare Realtime TURN (managed) when configured; otherwise
        falls back to a self-hosted coturn via its use-auth-secret (REST) scheme:
        the username is an expiry timestamp and the credential is
        base64(HMAC-SHA1(secret, username)), so Odoo never ships the long-lived
        TURN secret to the browser."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        # comm.turn.disable=1 → hand the browser NO ICE servers. Host candidates
        # then gather instantly (no STUN/TURN round-trips), which matters when
        # the agent machine has interfaces that can't reach the TURN server and
        # stall JsSIP's non-trickle wait for gathering-complete. Only viable when
        # agent and Asterisk can reach each other directly (same LAN/tailnet).
        if ICP.get_param('comm.turn.disable') == '1':
            return []
        cf = cloudflare_ice_servers(self.env, ttl=int(
            ICP.get_param('comm.turn.ttl') or 86400))
        if cf:
            return cf
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
