# -*- coding: utf-8 -*-
"""Fixed fees: what a provider charges whether or not anything is used.

Each fee is put on the event ledger in the month it falls in, so the spend
overview, the statement and the budget count it without sums of their own.
A deposit is the exception: it is money held, not a cost, and never reaches
the ledger. The reports show it beside the totals instead.
"""
from datetime import datetime, time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .comm_billing_rate_card import CHANNEL_SELECTION

KIND_SELECTION = [
    ('monthly', 'Every month'),
    ('once', 'Once'),
    ('deposit', 'Deposit, refundable'),
]
# A change to any of these changes the charges already on the ledger.
SYNC_FIELDS = {'name', 'provider', 'channel', 'source', 'kind', 'date_from',
               'date_until', 'amount'}


class CommBillingFee(models.Model):
    _name = 'comm.billing.fee'
    _description = 'Fixed fee from a communications provider'
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Fee', required=True,
                       help='What the provider calls it, e.g. USSD hosting.')
    provider = fields.Char(required=True, index=True,
                           help='As written on the billing events, e.g. Connect Mobile, '
                                'so the fee lands under the same provider on the statement.')
    channel = fields.Selection(CHANNEL_SELECTION, required=True, default='ussd')
    source = fields.Selection(
        selection=[('chat2work', 'Chat2Work'),
                   ('contact_centre', 'Contact Centre'),
                   ('other', 'Not attributed')],
        string='Used by', required=True, default='other',
        help='Which part of the business the fee is paid for.')
    kind = fields.Selection(KIND_SELECTION, string='How often', required=True,
                            default='monthly',
                            help='Every month: charged in full for each month from the '
                                 'start date. Once: charged on the start date only. '
                                 'Deposit: money the provider holds and gives back; it '
                                 'is shown beside the totals and never counted as a cost.')
    date_from = fields.Date(string='From', required=True,
                            default=fields.Date.context_today,
                            help='The first day the fee applies, or the day a once-off '
                                 'fee or a deposit is charged.')
    date_until = fields.Date(string='Until',
                             help='The last day the fee applies, or the day a deposit '
                                  'came back. Leave empty while it runs.')
    vat_pct = fields.Float(string='VAT (%)', default=15.0,
                           help='Added on the statement to show what is actually paid. '
                                'Use 0 for a provider that charges no VAT.')
    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(string='Amount, before VAT', required=True)
    note = fields.Char()
    event_ids = fields.One2many('comm.billing.event', 'fee_id', readonly=True)

    @api.constrains('amount', 'vat_pct', 'date_from', 'date_until')
    def _check_values(self):
        for fee in self:
            if fee.amount <= 0:
                raise ValidationError(_('A fee needs an amount above zero.'))
            if not 0 <= fee.vat_pct <= 100:
                raise ValidationError(_('VAT must be between 0 and 100 percent.'))
            if fee.date_until and fee.date_until < fee.date_from:
                raise ValidationError(_('A fee cannot end before it starts.'))

    # ------------------------------------------------------------------
    # Putting the fee on the ledger
    # ------------------------------------------------------------------
    def _charge_days(self, today):
        """{first day of the month: day the charge is dated} up to `today`.
        A monthly fee is charged in full for every month it touches, on the
        first of the month (its start date, in the month it starts)."""
        self.ensure_one()
        if self.kind == 'deposit' or self.date_from > today:
            return {}
        if self.kind == 'once':
            return {self.date_from.replace(day=1): self.date_from}
        days = {}
        month = self.date_from.replace(day=1)
        last = min(self.date_until or today, today)
        while month <= last:
            days[month] = max(month, self.date_from)
            month += relativedelta(months=1)
        return days

    def _event_vals(self, month, day):
        self.ensure_one()
        Event = self.env['comm.billing.event']
        # Noon, so the charge stays on its day in any time zone the reports use.
        at = datetime.combine(day, time(12, 0))
        return dict(
            event_date=at, channel=self.channel, provider=self.provider,
            category='fixed_fee', unit='fee', unit_qty=1.0, source=self.source,
            fee_id=self.id, fee_month=month,
            **Event._fixed_price(self.amount, self.currency_id, self.provider, at))

    def _sync(self):
        """Make the ledger agree with these fees: add the months that are
        missing, correct the ones that changed, drop the ones that no longer
        apply. Safe to run as often as needed."""
        Event = self.env['comm.billing.event'].sudo()
        today = self.env['comm.billing.report']._today()
        for fee in self.sudo():
            wanted = fee._charge_days(today)
            have = {}
            for event in fee.event_ids:
                if event.fee_month in wanted and event.fee_month not in have:
                    have[event.fee_month] = event
                else:
                    event.unlink()
            for month, day in wanted.items():
                vals = fee._event_vals(month, day)
                if month in have:
                    have[month].write(vals)
                else:
                    Event.create(vals)

    @api.model
    def _cron_post(self):
        """Daily: a new month's fees appear on its first day."""
        self.sudo().search([])._sync()

    @api.model_create_multi
    def create(self, vals_list):
        fees = super().create(vals_list)
        fees._sync()
        return fees

    def write(self, vals):
        res = super().write(vals)
        if SYNC_FIELDS & set(vals):
            self._sync()
        return res
