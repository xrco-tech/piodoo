# -*- coding: utf-8 -*-
"""Monthly budget, per-channel limits and the warnings they trigger."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ledger channel -> budget field
LIMIT_FIELDS = {
    'whatsapp': 'limit_whatsapp',
    'voice': 'limit_voice',
    'other': 'limit_ai',
    'sms': 'limit_sms',
    'ussd': 'limit_ussd',
}


class CommBillingBudget(models.Model):
    _name = 'comm.billing.budget'
    _description = 'Communication monthly budget'
    _inherit = ['mail.thread']
    _rec_name = 'display_name'

    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(
        string='Monthly budget', tracking=True,
        help='Most we want to spend in a month, all channels together. '
             'The same amount applies every month until it is changed.')
    limit_whatsapp = fields.Monetary(string='WhatsApp', tracking=True)
    limit_voice = fields.Monetary(string='Voice', tracking=True)
    limit_ai = fields.Monetary(string='AI', tracking=True)
    limit_sms = fields.Monetary(string='SMS', tracking=True)
    limit_ussd = fields.Monetary(string='USSD', tracking=True)
    limits_total = fields.Monetary(compute='_compute_limits_total')
    limits_note = fields.Char(compute='_compute_limits_total')

    warn_pct = fields.Boolean(string='Spending reaches part of the budget',
                              default=True)
    warn_pct_level = fields.Integer(string='Warn at (%)', default=80)
    warn_forecast = fields.Boolean(
        string='The month is likely to end over budget', default=True)
    warn_channel = fields.Boolean(
        string='A channel goes over its own limit', default=True)
    warn_day = fields.Boolean(string='One day costs more than')
    warn_day_amount = fields.Monetary(string='Daily amount')
    alert_ids = fields.One2many('comm.billing.budget.alert', 'budget_id',
                                string='Warnings sent', readonly=True)

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)',
         'There is already a budget for this company.'),
    ]

    @api.depends('company_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _('Budget and warnings')

    @api.depends('amount', 'limit_whatsapp', 'limit_voice', 'limit_ai',
                 'limit_sms', 'limit_ussd')
    def _compute_limits_total(self):
        for rec in self:
            total = sum(rec[f] for f in LIMIT_FIELDS.values())
            rec.limits_total = total
            if not total:
                rec.limits_note = _('No channel limits set.')
            elif rec.amount and abs(total - rec.amount) < 0.005:
                rec.limits_note = _('The limits add up to the monthly budget.')
            elif rec.amount and total > rec.amount:
                rec.limits_note = _('The limits add up to more than the monthly budget.')
            else:
                rec.limits_note = _('The limits add up to less than the monthly budget.')

    @api.constrains('amount', 'limit_whatsapp', 'limit_voice', 'limit_ai',
                    'limit_sms', 'limit_ussd', 'warn_pct_level', 'warn_day_amount')
    def _check_amounts(self):
        for rec in self:
            values = [rec.amount, rec.warn_day_amount] + [rec[f] for f in LIMIT_FIELDS.values()]
            if any(v < 0 for v in values):
                raise ValidationError(_('Budget amounts cannot be negative.'))
            if rec.warn_pct and not 1 <= rec.warn_pct_level <= 100:
                raise ValidationError(_('The warning level must be between 1 and 100 percent.'))

    def limits(self):
        """{ledger channel: limit} for the channels that have one."""
        self.ensure_one()
        return {ch: self[f] for ch, f in LIMIT_FIELDS.items() if self[f]}

    @api.model
    def _for_company(self, company=None):
        return self.sudo().search(
            [('company_id', '=', (company or self.env.company).id)], limit=1)

    @api.model
    def action_open(self):
        """Open this company's budget, creating the empty record on first use."""
        budget = self._for_company()
        if not budget:
            self.check_access('create')
            budget = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget and warnings'),
            'res_model': self._name,
            'res_id': budget.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Warnings
    # ------------------------------------------------------------------
    def _recipients(self):
        group = self.env.ref('comm_billing_core.group_billing_administrator')
        return group.users.filtered(
            lambda u: u.active and self.company_id in u.company_ids).partner_id

    def _warn(self, month, kind, subject, body):
        """Send one warning per (month, kind). Returns True when it was sent."""
        self.ensure_one()
        Alert = self.env['comm.billing.budget.alert']
        if Alert.search_count([('budget_id', '=', self.id), ('month', '=', month),
                               ('kind', '=', kind)]):
            return False
        Alert.create({'budget_id': self.id, 'month': month, 'kind': kind,
                      'name': subject})
        partners = self._recipients()
        if partners:
            self.message_notify(partner_ids=partners.ids, subject=subject, body=body)
        return True

    def _check_warnings(self):
        Report = self.env['comm.billing.report']
        for budget in self:
            state = Report.with_company(budget.company_id)._budget_state(budget)
            if not state:
                continue
            money = lambda v: budget.currency_id.format(v)  # noqa: E731
            month = state['month']
            name = state['month_label']
            if (budget.warn_pct and budget.amount
                    and state['spent'] >= budget.amount * budget.warn_pct_level / 100.0):
                budget._warn(month, 'pct', _(
                    'Comms spend has reached %(pct)s%% of the %(month)s budget',
                    pct=budget.warn_pct_level, month=name), _(
                    '%(spent)s of the %(budget)s budget for %(month)s is spent.',
                    spent=money(state['spent']), budget=money(budget.amount), month=name))
            # A forecast from the first few days of a month swings too much to act on.
            if (budget.warn_forecast and budget.amount and state['forecast']
                    and state['days_elapsed'] >= 7 and state['forecast'] > budget.amount):
                budget._warn(month, 'forecast', _(
                    'Comms spend is likely to end %(month)s over budget', month=name), _(
                    'At the pace so far, %(month)s will come to about %(forecast)s, '
                    'which is %(over)s over the %(budget)s budget.',
                    month=name, forecast=money(state['forecast']),
                    over=money(state['forecast'] - budget.amount),
                    budget=money(budget.amount)))
            if budget.warn_channel:
                for channel, limit in budget.limits().items():
                    spent = state['channels'].get(channel, 0.0)
                    if spent > limit:
                        label = Report._channel_label(channel)
                        budget._warn(month, 'channel:%s' % channel, _(
                            '%(channel)s has gone over its limit for %(month)s',
                            channel=label, month=name), _(
                            '%(channel)s has cost %(spent)s this month, over its '
                            '%(limit)s limit.', channel=label, spent=money(spent),
                            limit=money(limit)))
            if budget.warn_day and budget.warn_day_amount:
                for day, cost in state['days'].items():
                    if cost > budget.warn_day_amount:
                        budget._warn(month, 'day:%s' % day, _(
                            'Comms spend on %(day)s was unusually high', day=day), _(
                            '%(day)s cost %(cost)s, more than the %(limit)s a day '
                            'you asked to be warned about.', day=day,
                            cost=money(cost), limit=money(budget.warn_day_amount)))

    @api.model
    def _cron_check_budgets(self):
        self.sudo().search([])._check_warnings()


class CommBillingBudgetAlert(models.Model):
    _name = 'comm.billing.budget.alert'
    _description = 'Communication budget warning sent'
    _order = 'create_date desc, id desc'

    budget_id = fields.Many2one('comm.billing.budget', required=True,
                                ondelete='cascade', index=True)
    month = fields.Date(required=True, index=True)
    kind = fields.Char(required=True)
    name = fields.Char(string='Warning', required=True)

    _sql_constraints = [
        ('alert_uniq', 'unique(budget_id, month, kind)',
         'This warning was already sent for the month.'),
    ]
