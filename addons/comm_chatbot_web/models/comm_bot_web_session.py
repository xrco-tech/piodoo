# -*- coding: utf-8 -*-
"""Persistent web-widget sessions.

Anonymous website visitors get a token cookie'd in localStorage; the token
maps to a comm.bot.web.session which owns the conversation on the comm.bot
side. Sessions expire after conversation_timeout_hours of inactivity.
"""
import logging
import uuid
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommBotWebSession(models.Model):
    _name = 'comm.bot.web.session'
    _description = 'Web chat widget session'
    _order = 'created_at desc'

    token = fields.Char(required=True, index=True,
        default=lambda self: uuid.uuid4().hex,
        help='Opaque identifier used by the widget to re-attach across page loads.')
    bot_id = fields.Many2one('comm.bot', required=True, ondelete='cascade')
    conversation_id = fields.Many2one('comm.conversation', ondelete='set null')
    partner_id = fields.Many2one('res.partner')
    referer = fields.Char(help='Origin URL where the widget was embedded.')
    user_agent = fields.Char()
    created_at = fields.Datetime(default=fields.Datetime.now)
    last_activity_at = fields.Datetime(default=fields.Datetime.now)
    closed = fields.Boolean(index=True)
    is_preview = fields.Boolean(default=False,
        help='Sessions opened from the device simulator — never actually send.')

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
            if s.conversation_id and s.conversation_id.lifecycle_state in (
                    'open', 'waiting'):
                s.conversation_id.close(outcome='web_session_closed',
                                          state='closed')

    @api.model
    def cron_purge_stale(self):
        """Purge closed + orphaned sessions older than 30 days."""
        cutoff = fields.Datetime.now() - timedelta(days=30)
        stale = self.search([
            '|', ('closed', '=', True), ('last_activity_at', '<', cutoff),
        ], limit=500)
        stale.sudo().unlink()
