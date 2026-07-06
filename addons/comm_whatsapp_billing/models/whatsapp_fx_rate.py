# -*- coding: utf-8 -*-
from odoo import models, fields, api


class WhatsappFxRate(models.Model):
    _name = 'whatsapp.fx.rate'
    _description = 'USD -> local currency FX rate (daily)'
    _order = 'date desc, currency_id'
    _rec_name = 'display_name'

    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    currency_id = fields.Many2one('res.currency', required=True, index=True)
    rate = fields.Float(required=True, digits=(12, 6),
        help='1 USD = this many units of currency_id on this date.')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('date_currency_uniq', 'unique(date, currency_id)',
         'Only one FX rate per currency per date.'),
    ]

    @api.depends('date', 'currency_id.name', 'rate')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.date} 1 USD = {rec.rate:.4f} {rec.currency_id.name or ""}'

    @api.model
    def rate_for(self, currency, on_date):
        """Return the most recent FX rate for `currency` on/before `on_date`.
        Falls back to 1.0 if none found (i.e. treat as USD)."""
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.today()
        row = self.search([
            ('currency_id', '=', currency.id),
            ('date', '<=', on_date),
        ], order='date desc', limit=1)
        return row.rate if row else 1.0
