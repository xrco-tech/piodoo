# -*- coding: utf-8 -*-
"""Provider monthly billing FX override.

Providers (Meta, Infobip, etc.) typically bill in the account's currency
using their own monthly applied FX rate. Storing that rate here lets the
ledger reconcile exactly against the provider's invoice.
"""
from odoo import models, fields, api


class CommBillingFxRate(models.Model):
    _name = 'comm.billing.fx.rate'
    _description = 'Provider monthly billing FX override (USD -> local)'
    _order = 'date desc, provider, currency_id'
    _rec_name = 'display_name'

    date = fields.Date(string='Month', required=True, index=True,
        default=fields.Date.context_today,
        help='First day of the month this FX rate applies to.')
    currency_id = fields.Many2one('res.currency', required=True, index=True)
    provider = fields.Char(index=True,
        help='Which provider\'s billing FX this represents (e.g. Meta, Infobip). '
             'Leave empty for a house-wide default.')
    rate = fields.Float(required=True, digits=(12, 6),
        help='1 USD = this many units of currency_id.')
    source = fields.Selection([
        ('provider', 'Provider monthly invoice'),
        ('manual',   'Manual override'),
    ], default='provider', required=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('date_currency_provider_uniq',
         'unique(date, currency_id, provider)',
         'Only one FX rate per (provider, currency, month).'),
    ]

    @api.depends('date', 'currency_id.name', 'rate', 'provider')
    def _compute_display_name(self):
        for rec in self:
            provider = f'[{rec.provider}] ' if rec.provider else ''
            rec.display_name = (f'{provider}{rec.date:%Y-%m} 1 USD = '
                                f'{rec.rate:.4f} {rec.currency_id.name or ""}')

    @api.model
    def _rate_for_month(self, currency, on_date, provider=None):
        """Return the provider-specific rate covering `on_date`'s month, or
        the house-wide default if no provider-specific row exists."""
        if not currency:
            return 0.0
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.today()
        month_start = on_date.replace(day=1)
        base = [
            ('currency_id', '=', currency.id),
            ('date', '<=', on_date),
            ('date', '>=', month_start),
        ]
        # 1. Provider-specific
        if provider:
            row = self.search(base + [('provider', '=', provider)],
                              order='date desc', limit=1)
            if row:
                return row.rate
        # 2. House-wide (provider empty)
        row = self.search(base + [('provider', '=', False)],
                          order='date desc', limit=1)
        if row:
            return row.rate
        # 3. Last resort: carry the most recent earlier rate forward, the
        #    provider's own first, then the house-wide one.
        past = [('currency_id', '=', currency.id), ('date', '<=', on_date)]
        for scope in ([provider] if provider else []) + [False]:
            row = self.search(past + [('provider', '=', scope)], order='date desc', limit=1)
            if row:
                return row.rate
        return 0.0

    # ---- Keep recorded charges in step with the rates ----
    def _affected_events(self):
        """Charges whose conversion may depend on these rates: everything
        from the earliest month touched, for the provider (or for everyone,
        when a house-wide rate changed, since it is other providers' fallback
        and the last resort for later months)."""
        if not self:
            return self.env['comm.billing.event']
        domain = [('event_date', '>=', fields.Datetime.to_datetime(
            min(self.mapped('date')).replace(day=1)))]
        providers = self.mapped('provider')
        if all(providers):
            domain.append(('provider', 'in', providers))
        return self.env['comm.billing.event'].sudo().search(domain)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._affected_events()._reconvert()
        return records

    def write(self, vals):
        before = self._affected_events()
        res = super().write(vals)
        (before | self._affected_events())._reconvert()
        return res

    def unlink(self):
        events = self._affected_events()
        res = super().unlink()
        events._reconvert()
        return res

