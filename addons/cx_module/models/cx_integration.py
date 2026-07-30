# -*- coding: utf-8 -*-
"""Integrations config + queued webhook dispatch.

- cx.integration.mcp              — external MCP servers.
- cx.integration.webhook          — outbound webhook definitions.
- cx.integration.webhook.delivery — the queue: one row per (webhook, event).

Events enqueue cheap delivery rows on the hot path (no HTTP); a cron
(`_cron_cx_dispatch`) does the actual POST off the hot path, with HMAC signing
and exponential-backoff retries. So message creation never blocks on an
external endpoint.
"""
import hashlib
import hmac
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_logger = logging.getLogger(__name__)

WEBHOOK_EVENTS = [
    ('conversation.opened', 'Conversation opened'),
    ('interaction.inbound', 'Inbound message'),
    ('interaction.outbound', 'Outbound message'),
    ('campaign.sent', 'Campaign sent'),
    ('all', 'All events'),
]


class CxIntegrationMcp(models.Model):
    _name = 'cx.integration.mcp'
    _description = 'UCX MCP Connector'
    _order = 'name'

    name = fields.Char(required=True)
    url = fields.Char(string='Server URL', required=True,
                      help='Endpoint of the MCP server (Streamable HTTP / SSE).')
    transport = fields.Selection(
        [('sse', 'SSE'), ('http', 'Streamable HTTP'), ('stdio', 'stdio')],
        default='sse', required=True)
    auth_token = fields.Char(string='Auth Token', groups='cx_module.group_cx_admin',
                             help='Bearer/API token sent to the MCP server.')
    active = fields.Boolean(default=True)
    description = fields.Text()


class CxIntegrationWebhook(models.Model):
    _name = 'cx.integration.webhook'
    _description = 'UCX Outbound Webhook'
    _order = 'name'

    name = fields.Char(required=True)
    target_url = fields.Char(string='Target URL', required=True)
    event = fields.Selection(WEBHOOK_EVENTS, required=True,
                             default='interaction.inbound')
    secret = fields.Char(groups='cx_module.group_cx_admin',
                         help='Shared secret; sent as an HMAC-SHA256 signature '
                              'header (X-CX-Signature) on every delivery.')
    active = fields.Boolean(default=True)
    max_attempts = fields.Integer(default=5,
                                  help='Give up after this many failed attempts.')
    last_triggered_at = fields.Datetime(readonly=True)
    last_status = fields.Char(readonly=True)
    delivery_ids = fields.One2many('cx.integration.webhook.delivery', 'webhook_id',
                                   string='Deliveries')

    def action_cx_test_webhook(self):
        """User-initiated: POST a sample payload now (synchronous), to the
        admin's own endpoint. Bypasses the queue."""
        for hook in self:
            ok, status = hook._post({'event': 'test', 'webhook': hook.name,
                                     'message': 'UCX test delivery'})
            hook.write({'last_status': status, 'last_triggered_at': fields.Datetime.now()})
        return True

    def _post(self, payload):
        """POST the payload; return (ok, status_string). HMAC-signs when a
        secret is set."""
        self.ensure_one()
        if not requests:
            return False, 'requests library unavailable'
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.secret:
            sig = hmac.new(self.secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            headers['X-CX-Signature'] = 'sha256=%s' % sig
        try:
            resp = requests.post(self.target_url, data=body, headers=headers, timeout=10)
            return (200 <= resp.status_code < 300), 'HTTP %s' % resp.status_code
        except Exception as e:  # pragma: no cover - endpoint-side failures
            _logger.warning('cx webhook %s post failed: %s', self.id, e)
            return False, 'error: %s' % e

    @api.model
    def _cx_enqueue_event(self, event_code, payload):
        """Hot-path helper: create pending delivery rows for active webhooks
        matching this event. No HTTP — the cron delivers. Runs sudo so the
        triggering user needn't have webhook-config access."""
        hooks = self.sudo().search(
            [('active', '=', True), ('event', 'in', [event_code, 'all'])])
        if not hooks:
            return
        Delivery = self.env['cx.integration.webhook.delivery'].sudo()
        body = json.dumps(payload)
        Delivery.create([
            {'webhook_id': hook.id, 'event': event_code, 'payload': body}
            for hook in hooks
        ])


class CxIntegrationWebhookDelivery(models.Model):
    _name = 'cx.integration.webhook.delivery'
    _description = 'UCX Webhook Delivery'
    _order = 'create_date desc'

    webhook_id = fields.Many2one('cx.integration.webhook', required=True,
                                 ondelete='cascade', index=True)
    event = fields.Char(readonly=True)
    payload = fields.Text(readonly=True)
    state = fields.Selection(
        [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')],
        default='pending', index=True, readonly=True)
    attempts = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(index=True, readonly=True)
    last_error = fields.Char(readonly=True)

    @api.model
    def _cron_cx_dispatch(self, batch=25):
        """Deliver due pending rows. Backs off failures exponentially and gives
        up after the webhook's max_attempts."""
        now = fields.Datetime.now()
        due = self.search([
            ('state', '=', 'pending'),
            '|', ('next_attempt_at', '=', False), ('next_attempt_at', '<=', now),
        ], limit=batch, order='create_date')
        for delivery in due:
            try:
                payload = json.loads(delivery.payload or '{}')
            except (ValueError, TypeError):
                payload = {'raw': delivery.payload}
            ok, status = delivery.webhook_id._post(payload)
            attempts = delivery.attempts + 1
            vals = {'attempts': attempts, 'last_error': status}
            if ok:
                vals['state'] = 'sent'
            elif attempts >= (delivery.webhook_id.max_attempts or 5):
                vals['state'] = 'failed'
            else:
                # exponential backoff, capped at ~64 min
                vals['next_attempt_at'] = now + timedelta(minutes=2 ** min(attempts, 6))
            delivery.write(vals)
            delivery.webhook_id.write({'last_status': status, 'last_triggered_at': now})
