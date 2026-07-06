# -*- coding: utf-8 -*-
"""WhatsApp-specific free-window tracking, kept in core so other channels
could reuse the shape if a provider ever introduces something similar."""
from datetime import timedelta
from odoo import models, fields, api


class CommBillingFreeWindow(models.Model):
    _name = 'comm.billing.free.window'
    _description = 'Free-messaging window (24h CS or 72h entry point)'
    _order = 'opened_at desc'
    _rec_name = 'display_name'

    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
    ], required=True, default='whatsapp', index=True)
    partner_id = fields.Many2one('res.partner', index=True)
    wa_id = fields.Char(index=True,
        help='WhatsApp ID / MSISDN. Used when a partner is not linked yet.')
    account_ref = fields.Char(index=True,
        help='Free-text account identifier (e.g. WABA name/id).')
    window_type = fields.Selection([
        ('cs_24h',    'Customer Service (24h)'),
        ('entry_72h', 'Free Entry Point (72h)'),
    ], required=True, default='cs_24h')
    opened_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    expires_at = fields.Datetime(required=True, index=True)
    source_ref = fields.Char()
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('wa_id', 'window_type', 'opened_at')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.wa_id or "?"} / {rec.window_type} @ {rec.opened_at}'

    @api.model
    def open_window(self, account_ref, wa_id, partner=None,
                    window_type='cs_24h', opened_at=None, source_ref=None):
        opened_at = opened_at or fields.Datetime.now()
        hours = 24 if window_type == 'cs_24h' else 72
        expires = opened_at + timedelta(hours=hours)

        existing = self.search([
            ('account_ref', '=', account_ref or False),
            ('wa_id', '=', wa_id),
            ('window_type', '=', window_type),
            ('expires_at', '>=', opened_at),
        ], limit=1)
        if existing:
            if expires > existing.expires_at:
                existing.write({'expires_at': expires, 'opened_at': opened_at})
            return existing

        return self.create({
            'account_ref': account_ref,
            'wa_id': wa_id,
            'partner_id': partner.id if partner else False,
            'window_type': window_type,
            'opened_at': opened_at,
            'expires_at': expires,
            'source_ref': source_ref,
        })

    @api.model
    def covers(self, account_ref, wa_id, at_datetime, window_type='cs_24h'):
        at_datetime = at_datetime or fields.Datetime.now()
        return bool(self.search_count([
            ('account_ref', '=', account_ref or False),
            ('wa_id', '=', wa_id),
            ('window_type', '=', window_type),
            ('opened_at', '<=', at_datetime),
            ('expires_at', '>=', at_datetime),
        ]))
