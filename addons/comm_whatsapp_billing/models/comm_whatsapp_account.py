# -*- coding: utf-8 -*-
from odoo import models, fields, api


def _default_billing_currency(env):
    return env.company.currency_id.id


class CommWhatsappAccount(models.Model):
    _inherit = 'comm.whatsapp.account'

    country_id = fields.Many2one('res.country', string='Business Country',
        help='Country of the WABA account. Drives auth-international detection.')
    billing_currency_id = fields.Many2one('res.currency',
        string='Billing Currency',
        default=lambda self: _default_billing_currency(self.env),
        help='Currency used to display and reconcile costs. Defaults to the '
             'company currency (typically ZAR).')
    default_fx_rate = fields.Float(string='Fallback USD → local FX',
        digits=(12, 6),
        help='Used when neither the Meta monthly override nor Odoo currency '
             'rates are available. Example: 18.5 = 1 USD costs R18.50.')
    billing_event_ids = fields.One2many('whatsapp.billing.event', 'account_id',
        string='Billing Events')
    billing_mtd_usd = fields.Float(string='MTD Cost (USD)',
        compute='_compute_billing_mtd', digits=(12, 4))
    billing_mtd_local = fields.Float(string='MTD Cost (local)',
        compute='_compute_billing_mtd', digits=(12, 4))

    def _compute_billing_mtd(self):
        Event = self.env['whatsapp.billing.event']
        today = fields.Date.today()
        start = fields.Datetime.to_datetime(today.replace(day=1))
        for acc in self:
            rows = Event.search([
                ('account_id', '=', acc.id),
                ('event_date', '>=', start),
            ])
            acc.billing_mtd_usd = sum(rows.mapped('price_usd'))
            acc.billing_mtd_local = sum(rows.mapped('price_local'))
