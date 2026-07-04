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

    # Token health — populated by the daily cron and by any manual
    # "Check Token" click. When the token silently expires Meta
    # stops delivering webhooks; this catches that class of failure
    # before real calls / sync attempts hit it.
    token_status = fields.Selection([
        ('unchecked',   'Not checked yet'),
        ('valid',       'Valid'),
        ('expired',     'Expired'),
        ('unreachable', 'Unreachable'),
    ], string="Token Status", default='unchecked', readonly=True,
       tracking=True, index='btree')
    token_last_checked = fields.Datetime(
        string="Token Last Checked", readonly=True,
    )
    token_last_error = fields.Char(
        string="Token Last Error", readonly=True,
        help="Error message from the most recent token probe, if any.",
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

    def action_simulate_call_ringing(self):
        """Fire the fake ringing bus event to the current user so we can
        end-to-end test the popup + WebRTC pipeline without needing Meta
        to deliver a real call event. Isolates the frontend path from
        anything Meta might be doing wrong."""
        # Sample minimum-viable SDP offer — parseable by browser but not
        # routable to any real endpoint. Enough to prove the popup +
        # RTCPeerConnection wiring runs to Accept.
        sample_offer = (
            "v=0\r\n"
            "o=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
            "s=-\r\n"
            "t=0 0\r\n"
            "a=group:BUNDLE 0\r\n"
            "a=msid-semantic: WMS *\r\n"
            "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
            "c=IN IP4 0.0.0.0\r\n"
            "a=rtcp:9 IN IP4 0.0.0.0\r\n"
            "a=ice-ufrag:test\r\n"
            "a=ice-pwd:testpasswordtestpassword\r\n"
            "a=fingerprint:sha-256 "
            "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:"
            "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99\r\n"
            "a=setup:actpass\r\n"
            "a=mid:0\r\n"
            "a=recvonly\r\n"
            "a=rtcp-mux\r\n"
            "a=rtpmap:111 opus/48000/2\r\n"
        )
        CallLog = self.env.get('whatsapp.call.log')
        if CallLog is None:
            raise UserError(
                "comm_whatsapp_calling isn't installed. Install it via "
                "Apps → Update Apps List, then retry."
            )
        call_log = CallLog.sudo().create({
            'call_id':        f"simulated_{self.env.uid}_{fields.Datetime.now().isoformat()}",
            'call_direction': 'incoming',
            'from_number':    '+12345000000',
            'to_number':      self.phone_number or self.phone_number_id or 'WABA',
            'sdp_offer':      sample_offer,
            'call_status':    'ringing',
            'meta_phone_number_id': self.phone_number_id or '',
        })

        # Fire the bus event directly (targeting the current user only,
        # not everyone, so we don't bother other logged-in users).
        payload = {
            'type':          'whatsapp_incoming_call',
            'call_log_id':   call_log.id,
            'partner_id':    False,
            'partner_name':  '(simulated) Test Caller',
            'from_number':   call_log.from_number,
            'call_timestamp': (call_log.call_timestamp.isoformat()
                               if call_log.call_timestamp else None),
            'sdp_offer':     sample_offer,
        }
        # Target the current user's partner — Odoo 18 auto-subscribes
        # each session to its partner channel, so this is the only
        # reliably-delivered per-user push.
        partner = self.env.user.partner_id
        if partner:
            self.env['bus.bus'].sudo()._sendone(
                partner,
                'whatsapp_incoming_call',
                payload,
            )
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title':   'Simulated call fired',
                'message': (
                    f"Sent a fake ringing event to your user. If the popup "
                    f"appears, the bus + browser path is fine and the issue "
                    f"is upstream (Meta not delivering webhooks). If nothing "
                    f"appears, check the browser console for [wa-call] logs."
                ),
                'type':    'success',
                'sticky':  True,
            },
        }

    def action_fix_base_url_to_https(self):
        """One-click helper: rewrite web.base.url from http:// to https://
        so nothing downstream generates non-Meta-compatible callback URLs
        or plain-text notification links."""
        icp = self.env['ir.config_parameter'].sudo()
        base = icp.get_param('web.base.url', '')
        if not base:
            raise UserError("web.base.url is empty; nothing to fix.")
        if not base.startswith('http://'):
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title':   'Already HTTPS',
                    'message': f"web.base.url is already {base}.",
                    'type':    'info', 'sticky': False,
                },
            }
        new_url = 'https://' + base[len('http://'):]
        icp.set_param('web.base.url', new_url)
        # Freeze the base URL so no request re-derives it from the
        # HTTP host header on the next inbound.
        icp.set_param('web.base.url.freeze', 'True')
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title':   'Base URL updated',
                'message': f"web.base.url is now {new_url} and frozen.",
                'type':    'success', 'sticky': False,
            },
        }

    def action_diagnose_calling(self):
        """Poke Meta to check every prereq for browser-based WhatsApp
        calls on this WABA. Returns a sticky notification with one line
        per check so the user knows exactly what to fix."""
        self.ensure_one()
        if not self.access_token or not self.phone_number_id \
                or not self.business_account_id:
            raise UserError(
                "This account needs access_token, phone_number_id and "
                "business_account_id populated before diagnostics can run."
            )
        headers = {'Authorization': f'Bearer {self.access_token}'}
        checks = []

        # 1. Token validity — sanity ping against the phone_number_id.
        try:
            r = requests.get(
                f"https://graph.facebook.com/v18.0/{self.phone_number_id}"
                "?fields=display_phone_number",
                headers=headers, timeout=15,
            )
            if r.status_code == 200:
                checks.append("✅ Access token is valid.")
            else:
                err = (r.json() or {}).get('error', {}).get(
                    'message', r.text or f"HTTP {r.status_code}")
                checks.append(f"❌ Access token failed: {err}")
                return self._diag_notification(checks)
        except requests.exceptions.RequestException as e:
            checks.append(f"❌ Network error hitting Meta: {e}")
            return self._diag_notification(checks)

        # 2. WABA-level app subscription. GET /subscribed_apps returns
        #    the apps subscribed to receive webhooks for this WABA;
        #    per-field selection (messages / calls / etc.) lives on the
        #    APP itself, not on the WABA, so we can't reliably enumerate
        #    field names from this endpoint. Confirm here that AT LEAST
        #    ONE app is subscribed, and remind the user to verify field
        #    selection in the App Dashboard.
        try:
            r = requests.get(
                f"https://graph.facebook.com/v18.0/"
                f"{self.business_account_id}/subscribed_apps",
                headers=headers, timeout=15,
            )
            if r.status_code == 200:
                subs = (r.json() or {}).get('data') or []
                fields_seen = set()
                app_names = []
                for sub in subs:
                    app_data = sub.get('whatsapp_business_api_data') \
                        or sub.get('app') or {}
                    if app_data.get('name'):
                        app_names.append(app_data['name'])
                    # Some tokens return subscribed_fields inline; use it
                    # opportunistically when present.
                    for f in (sub.get('subscribed_fields') or []):
                        fields_seen.add(
                            f.get('name') if isinstance(f, dict) else f
                        )
                if not subs:
                    checks.append(
                        "❌ No app is subscribed to this WABA. Go to Meta "
                        "App Dashboard → WhatsApp → Configuration → "
                        "Webhooks and click Subscribe."
                    )
                elif fields_seen and 'calls' not in fields_seen:
                    # Only assert absence when Meta actually returned the
                    # field list (older tokens) — otherwise we can't tell.
                    checks.append(
                        f"❌ Webhook subscription is missing the `calls` "
                        f"field for app '{', '.join(app_names) or 'unknown'}'. "
                        f"Currently subscribed: {sorted(fields_seen)}"
                    )
                else:
                    checks.append(
                        f"✅ App{'s' if len(app_names) != 1 else ''} "
                        f"subscribed to this WABA: "
                        f"{', '.join(app_names) or '(unnamed)'}. "
                        f"Per-field selection is only visible in the App "
                        f"Dashboard — confirm `calls`, `messages`, and "
                        f"`message_template_status_update` are ticked."
                    )
            else:
                err = (r.json() or {}).get('error', {}).get(
                    'message', r.text or f"HTTP {r.status_code}")
                checks.append(f"❌ Could not read subscribed_apps: {err}")
        except requests.exceptions.RequestException as e:
            checks.append(f"❌ Network error on subscribed_apps: {e}")

        # 3. Business Calling API enrollment — POST to /{PNID}/calls with
        #    a bogus payload. Meta returns three flavours of error:
        #      * 4200x / "not authorized" → not enrolled.
        #      * 100 / 131009 / 2494010 → endpoint accepted our schema, then
        #        rejected our body. That means calling IS enrolled.
        #      * anything else → inconclusive.
        try:
            r = requests.post(
                f"https://graph.facebook.com/v18.0/{self.phone_number_id}/calls",
                headers={**headers, 'Content-Type': 'application/json'},
                json={"messaging_product": "whatsapp"},  # missing "action"
                timeout=15,
            )
            body = r.json() if r.text else {}
            err = body.get('error', {})
            code = err.get('code')
            subcode = err.get('error_subcode')
            emsg = err.get('message', '')
            # Codes emitted when Meta's schema validator saw the request
            # AND is willing to serve the endpoint (i.e. the API is on).
            calling_enabled_codes = {100, 131009}
            calling_enabled_subcodes = {2494010}
            if code in calling_enabled_codes \
                    or subcode in calling_enabled_subcodes \
                    or (code == 100 and 'action' in emsg.lower()):
                checks.append(
                    "✅ Business Calling API is enabled on this WABA."
                )
            elif r.status_code == 403 or code in (10, 200, 3) \
                    or 'not authorized' in emsg.lower() \
                    or 'permission' in emsg.lower():
                checks.append(
                    f"❌ Business Calling API is NOT enabled. Meta says: "
                    f"'{emsg}'. Enroll via WhatsApp Manager → Calling."
                )
            else:
                checks.append(
                    f"⚠️  Business Calling API check inconclusive "
                    f"(HTTP {r.status_code}, code {code}, subcode {subcode}"
                    f"): {emsg or r.text[:200]}"
                )
        except requests.exceptions.RequestException as e:
            checks.append(f"❌ Network error on calling probe: {e}")

        # 4. Odoo-side webhook URL — Meta rejects http:// webhooks; nudge
        #    the user toward the https equivalent when web.base.url is
        #    plain http.
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', ''
        )
        if not base:
            checks.append(
                "⚠️  web.base.url is not set; Meta cannot reach your "
                "webhook until it is."
            )
        else:
            https_base = base.replace('http://', 'https://', 1) \
                if base.startswith('http://') else base
            checks.append(
                f"ℹ️  Meta webhook must POST to: "
                f"{https_base}/whatsapp/webhook"
            )
            if base.startswith('http://'):
                checks.append(
                    "⚠️  web.base.url is `http://`. Meta only accepts "
                    "HTTPS webhook URLs — make sure the URL you paste "
                    "into Meta App Dashboard starts with `https://` "
                    "(your Cloudflare tunnel is already terminating TLS)."
                )

        return self._diag_notification(checks)

    def _diag_notification(self, lines):
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'WhatsApp Calling diagnostics',
                'message': '\n'.join(lines),
                'type':    ('success'
                            if all('✅' in l or 'ℹ️' in l for l in lines)
                            else 'warning'),
                'sticky':  True,
            },
        }

    # ── Token watchdog ────────────────────────────────────────────────

    def _probe_token(self):
        """Ping Meta with this account's token. Updates token_status,
        token_last_checked, token_last_error. Returns the new status
        so the cron can decide whether to notify."""
        self.ensure_one()
        if not self.access_token or not self.phone_number_id:
            self.write({
                'token_status':      'unchecked',
                'token_last_checked': fields.Datetime.now(),
                'token_last_error':  "access_token or phone_number_id missing",
            })
            return 'unchecked'

        url = (
            f"https://graph.facebook.com/v18.0/{self.phone_number_id}"
            "?fields=display_phone_number"
        )
        headers = {'Authorization': f'Bearer {self.access_token}'}
        try:
            r = requests.get(url, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            self.write({
                'token_status':       'unreachable',
                'token_last_checked': fields.Datetime.now(),
                'token_last_error':   f"Network: {e}"[:255],
            })
            return 'unreachable'

        if r.status_code == 200:
            self.write({
                'token_status':       'valid',
                'token_last_checked': fields.Datetime.now(),
                'token_last_error':   False,
            })
            return 'valid'

        # Meta returns 401 with code 190 for expired tokens.
        err = {}
        try:
            err = (r.json() or {}).get('error', {})
        except Exception:
            pass
        code = err.get('code')
        msg = err.get('message') or r.text[:200] or f"HTTP {r.status_code}"
        if r.status_code in (401, 403) or code in (190, 102, 200):
            new_status = 'expired'
        else:
            new_status = 'unreachable'
        self.write({
            'token_status':       new_status,
            'token_last_checked': fields.Datetime.now(),
            'token_last_error':   msg[:255],
        })
        return new_status

    def action_check_token(self):
        """Manual 'Check Token' button — probes and returns a
        display_notification summarising the outcome."""
        self.ensure_one()
        status = self._probe_token()
        colours = {
            'valid':       ('success', 'Token is valid.'),
            'expired':     ('danger',  f"Token expired: {self.token_last_error}"),
            'unreachable': ('warning', f"Could not reach Meta: {self.token_last_error}"),
            'unchecked':   ('warning', self.token_last_error or 'Not checked.'),
        }
        typ, msg = colours.get(status, ('warning', status))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title':   f"Token check — {self.name}",
                'message': msg,
                'type':    typ,
                'sticky':  status != 'valid',
            },
        }

    @api.model
    def cron_probe_all_tokens(self):
        """Daily cron — probe every active account's token. When one
        transitions valid → expired, bus-push a sticky notification to
        every admin so someone gets alerted before real traffic hits it.
        """
        accounts = self.sudo().search([('active', '=', True)])
        newly_expired = self.env['comm.whatsapp.account']
        for acc in accounts:
            was = acc.token_status
            now = acc._probe_token()
            if now == 'expired' and was != 'expired':
                newly_expired |= acc

        if not newly_expired:
            return True

        # Notify every user in the admin group (Settings).
        admin_group = self.env.ref('base.group_erp_manager',
                                   raise_if_not_found=False)
        admins = admin_group.users if admin_group else self.env['res.users']
        if not admins:
            return True

        payload = {
            'type':     'whatsapp_token_expired',
            'accounts': [{
                'id':   a.id,
                'name': a.name,
                'error': a.token_last_error or '',
            } for a in newly_expired],
        }
        bus = self.env['bus.bus'].sudo()
        for u in admins:
            if u.partner_id:
                try:
                    bus._sendone(
                        u.partner_id,
                        'whatsapp_token_expired',
                        payload,
                    )
                except AttributeError:
                    break
        _logger.warning(
            "WhatsApp account tokens expired: %s. %d admins notified.",
            newly_expired.mapped('name'), len(admins),
        )
        return True

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
