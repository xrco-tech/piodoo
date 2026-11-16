# -*- coding: utf-8 -*-
"""What each provider actually invoiced for a month, to check our ledger against."""
from odoo import api, fields, models


class CommBillingInvoice(models.Model):
    _name = 'comm.billing.invoice'
    _description = 'Provider invoice total for a month'
    _order = 'month desc, provider'

    month = fields.Date(required=True, index=True,
                        default=lambda self: fields.Date.context_today(self).replace(day=1),
                        help='Any day in the month the invoice covers.')
    provider = fields.Char(required=True, index=True,
                           help='As written on the billing events, e.g. Meta, Anthropic.')
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(string='Invoiced, before VAT', required=True)
    reference = fields.Char(string='Invoice number')
    note = fields.Char()

    _sql_constraints = [
        ('month_provider_uniq', 'unique(month, provider, company_id)',
         'There is already an invoice total for this provider and month.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('month'):
                vals['month'] = fields.Date.to_date(vals['month']).replace(day=1)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('month'):
            vals['month'] = fields.Date.to_date(vals['month']).replace(day=1)
        return super().write(vals)
