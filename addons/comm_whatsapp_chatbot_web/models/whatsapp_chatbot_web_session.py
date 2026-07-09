# -*- coding: utf-8 -*-
"""Persistent web-widget sessions for WA chatbots.

Anonymous visitors get a token; the session model persists their
simulator session_state between requests so the WA chatbot engine's
`simulate_turn` can be called with continuity across HTTP hops.
"""
import logging
import uuid
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappChatbotWebSession(models.Model):
    _name = 'whatsapp.chatbot.web.session'
    _description = 'WA chatbot web widget session'
    _order = 'created_at desc'

    token = fields.Char(required=True, index=True,
        default=lambda self: uuid.uuid4().hex)
    chatbot_id = fields.Many2one('whatsapp.chatbot', required=True,
                                  ondelete='cascade')
    session_state = fields.Json(default=dict,
        help='Opaque session_state consumed by whatsapp.chatbot.message.'
             'simulate_turn — persisted across HTTP requests.')
    persona_name = fields.Char()
    persona_mobile = fields.Char()
    referer = fields.Char()
    user_agent = fields.Char()
    is_preview = fields.Boolean(default=False)
    created_at = fields.Datetime(default=fields.Datetime.now)
    last_activity_at = fields.Datetime(default=fields.Datetime.now)
    closed = fields.Boolean(index=True)

    _sql_constraints = [
        ('token_uniq', 'unique(token)', 'Session token must be unique.'),
    ]

    @api.model
    def get_by_token(self, token):
        if not token:
            return self.browse()
        return self.search([('token', '=', token), ('closed', '=', False)],
                            limit=1)

    def touch(self):
        for s in self:
            s.last_activity_at = fields.Datetime.now()

    def close(self):
        for s in self:
            s.closed = True

    @api.model
    def cron_purge_stale(self):
        cutoff = fields.Datetime.now() - timedelta(days=30)
        stale = self.search([
            '|', ('closed', '=', True), ('last_activity_at', '<', cutoff),
        ], limit=500)
        stale.sudo().unlink()
