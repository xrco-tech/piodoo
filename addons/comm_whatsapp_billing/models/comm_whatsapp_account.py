# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CommWhatsappAccount(models.Model):
    _inherit = 'comm.whatsapp.account'

    country_id = fields.Many2one('res.country', string='Business Country',
        help='Country of the WABA account. Drives auth-international detection.')
    billing_currency_id = fields.Many2one('res.currency',
        string='Billing Currency',
        help='Currency used to display costs (via whatsapp.fx.rate). '
             'USD if unset.')
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
