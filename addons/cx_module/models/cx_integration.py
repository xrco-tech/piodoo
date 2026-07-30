# -*- coding: utf-8 -*-
"""Phase — Integrations config (genuinely-new UCX models).

Two small config models surfaced under Configuration > Integrations:

- cx.integration.mcp     — external MCP servers the platform can connect to.
- cx.integration.webhook — outbound webhooks fired on UCX events.

These are configuration records. Webhook *delivery* on live events is
deliberately kept out of the message-creation hot path (a synchronous external
POST there would slow every inbound message); a user-initiated "Send test"
button verifies an endpoint on demand, and an event-driven delivery engine is a
follow-on.
"""
import hashlib
import hmac
import json
import logging

from odoo import fields, models

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
                              'header (X-CX-Signature).')
    active = fields.Boolean(default=True)
    last_triggered_at = fields.Datetime(readonly=True)
    last_status = fields.Char(readonly=True)

    def action_cx_test_webhook(self):
        """User-initiated: POST a sample payload to the target URL and record
        the result. Fires only when an admin clicks it, to their own endpoint."""
        for hook in self:
            hook._deliver({
                'event': 'test',
                'webhook': hook.name,
                'message': 'UCX test delivery',
            })
        return True

    def _deliver(self, payload):
        self.ensure_one()
        if not requests:
            self.last_status = 'requests library unavailable'
            return
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if self.secret:
            sig = hmac.new(self.secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
            headers['X-CX-Signature'] = 'sha256=%s' % sig
        try:
            resp = requests.post(self.target_url, data=body, headers=headers, timeout=10)
            self.last_status = 'HTTP %s' % resp.status_code
        except Exception as e:  # pragma: no cover - endpoint-side failures
            _logger.warning('cx webhook %s delivery failed: %s', self.id, e)
            self.last_status = 'error: %s' % e
        self.last_triggered_at = fields.Datetime.now()
