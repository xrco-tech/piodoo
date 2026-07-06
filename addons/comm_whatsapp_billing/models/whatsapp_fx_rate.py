# -*- coding: utf-8 -*-
"""Meta monthly billing FX override.

Meta bills WABA accounts in the account's currency using their own monthly
applied FX rate. Storing that rate here lets the ledger reconcile exactly
against Meta's invoice — otherwise we fall back to Odoo's `res.currency.rate`
(and if that's empty, the account's `default_fx_rate`).

Convention: one row per (currency, month). The `date` is the first day of
the month the rate applies to; `_rate_for_month` snaps to that when
querying.
"""
from odoo import models, fields, api


class WhatsappFxRate(models.Model):
    _name = 'whatsapp.fx.rate'
    _description = 'Meta monthly billing FX override (USD -> local)'
    _order = 'date desc, currency_id'
    _rec_name = 'display_name'

    date = fields.Date(string='Month', required=True, index=True,
        default=fields.Date.context_today,
        help='First day of the month this Meta FX rate applies to.')
    currency_id = fields.Many2one('res.currency', required=True, index=True)
    rate = fields.Float(required=True, digits=(12, 6),
        help='1 USD = this many units of currency_id, as applied by Meta '
             'for this billing month.')
    source = fields.Selection([
        ('meta',  'Meta monthly invoice'),
        ('manual','Manual override'),
    ], default='meta', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('date_currency_uniq', 'unique(date, currency_id)',
         'Only one Meta FX rate per currency per month.'),
    ]

    @api.depends('date', 'currency_id.name', 'rate')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (f'{rec.date:%Y-%m} 1 USD = {rec.rate:.4f} '
                                f'{rec.currency_id.name or ""}')

    @api.model
    def _rate_for_month(self, currency, on_date):
        """Return the Meta rate covering `on_date`'s month, or 0.0 if none."""
        if not currency:
            return 0.0
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.today()
        month_start = on_date.replace(day=1)
        row = self.search([
            ('currency_id', '=', currency.id),
            ('date', '<=', on_date),
            ('date', '>=', month_start.replace(day=1)),
        ], order='date desc', limit=1)
        if row:
            return row.rate
        # Fall back to most recent past rate — better than nothing
        row = self.search([
            ('currency_id', '=', currency.id),
            ('date', '<=', on_date),
        ], order='date desc', limit=1)
        return row.rate if row else 0.0
