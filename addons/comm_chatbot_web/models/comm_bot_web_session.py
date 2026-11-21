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

    # ── The preview's contact ────────────────────────────────────────────

    PREVIEW_REF = 'comm-chatbot-web-preview'

    @api.model
    def _preview_partner(self, name=None, mobile=None):
        """The one contact every preview of the widget runs as.

        A preview used to make a new contact each time it was opened, so
        they piled up in Contacts. It is one record now, kept archived: it
        does not show in Contacts, and a real message from the same number
        is never matched to it."""
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        partner = Partner.search([('ref', '=', self.PREVIEW_REF)], limit=1)
        vals = {'name': name or 'Web preview', 'mobile': mobile or '+27600000000'}
        if not partner:
            return Partner.create(dict(vals, ref=self.PREVIEW_REF, active=False))
        if partner.name != vals['name'] or partner.mobile != vals['mobile']:
            partner.write(vals)
        return partner

    @api.model
    def _archive_minted_preview_contacts(self):
        """Archive the contacts older previews left behind. Only contacts
        that are nothing but a preview's are touched: not one that is a
        user's, and not one with a conversation outside a preview."""
        Partner = self.env['res.partner'].sudo()
        previews = self.sudo().search([('is_preview', '=', True)])
        minted = previews.partner_id | Partner.search([
            ('name', '=', 'Web preview'), ('mobile', '=', '+27600000000')])
        minted = minted.filtered(lambda p: p.active and p.ref != self.PREVIEW_REF)
        if not minted:
            return minted
        users = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('partner_id', 'in', minted.ids)]).partner_id
        elsewhere = self.env['comm.conversation'].sudo().search([
            ('partner_id', 'in', minted.ids),
            ('id', 'not in', previews.conversation_id.ids),
        ]).partner_id
        minted -= users | elsewhere
        minted.write({'active': False})
        return minted
