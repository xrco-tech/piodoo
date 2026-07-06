# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


BACKFILL_CATEGORY_SELECTION = [
    ('all',                'All categories'),
    ('marketing',          'Marketing'),
    ('utility',            'Utility'),
    ('authentication',     'Authentication'),
    ('auth_international', 'Authentication-International'),
    ('service',            'Service'),
    ('call_minute',        'Call minutes'),
]


class WhatsappBillingBackfill(models.TransientModel):
    _name = 'whatsapp.billing.backfill'
    _description = 'Replay historical whatsapp.message / whatsapp.call.log into comm.billing.event'

    months = fields.Integer(string='Backfill last N months', default=3, required=True,
        help='0 = all history.')
    account_ids = fields.Many2many('comm.whatsapp.account',
        string='Accounts', help='Empty = ALL accounts.')
    include_messages = fields.Boolean(default=True)
    include_calls = fields.Boolean(default=True)
    category_filter = fields.Selection(BACKFILL_CATEGORY_SELECTION,
        default='all', required=True)
    only_missing = fields.Boolean(default=True)
    dry_run = fields.Boolean(default=True)

    messages_scanned = fields.Integer(readonly=True)
    messages_ingested = fields.Integer(readonly=True)
    calls_scanned = fields.Integer(readonly=True)
    calls_ingested = fields.Integer(readonly=True)
    result_html = fields.Html(readonly=True)

    def _cutoff(self):
        if not self.months:
            return False
        return fields.Datetime.now() - relativedelta(months=self.months)

    def _message_domain(self):
        domain = [('pricing_category', '!=', False)]
        cutoff = self._cutoff()
        if cutoff:
            domain.append(('message_timestamp', '>=', cutoff))
        if self.account_ids:
            domain.append(('account_id', 'in', self.account_ids.ids))
        if self.category_filter and self.category_filter != 'all':
            synonyms = {
                'marketing':          ['marketing'],
                'utility':            ['utility'],
                'authentication':     ['authentication'],
                'auth_international': ['authentication_international'],
                'service':            ['service', 'user_initiated',
                                       'referral_conversion'],
                'call_minute':        [],
            }
            wanted = synonyms.get(self.category_filter, [])
            if wanted:
                domain.append(('pricing_category', 'in', wanted))
            else:
                domain.append(('id', '=', 0))
        return domain

    def _call_domain(self):
        domain = [('call_status', '=', 'ended'), ('duration', '>', 0)]
        cutoff = self._cutoff()
        if cutoff:
            domain.append(('end_timestamp', '>=', cutoff))
        if self.account_ids:
            domain.append(('account_id', 'in', self.account_ids.ids))
        return domain

    def action_run(self):
        self.ensure_one()
        Event = self.env['comm.billing.event']
        ms = mi = cs = ci = 0

        if self.include_messages:
            messages = self.env['whatsapp.message'].search(self._message_domain())
            ms = len(messages)
            for msg in messages:
                if self.only_missing and Event.search_count([
                    ('source_model', '=', 'whatsapp.message'),
                    ('source_id', '=', msg.id),
                ]):
                    continue
                if self.dry_run:
                    mi += 1
                    continue
                try:
                    ev = Event._create_from_wa_message(msg)
                    if ev:
                        mi += 1
                except Exception as e:
                    _logger.warning('Backfill msg %s failed: %s', msg.id, e)

        if self.include_calls and self.category_filter in ('all', 'call_minute'):
            calls = self.env['whatsapp.call.log'].search(self._call_domain())
            cs = len(calls)
            for call in calls:
                if self.only_missing and Event.search_count([
                    ('source_model', '=', 'whatsapp.call.log'),
                    ('source_id', '=', call.id),
                ]):
                    continue
                if self.dry_run:
                    ci += 1
                    continue
                try:
                    ev = Event._create_from_wa_call(call)
                    if ev:
                        ci += 1
                except Exception as e:
                    _logger.warning('Backfill call %s failed: %s', call.id, e)

        self.write({
            'messages_scanned': ms, 'messages_ingested': mi,
            'calls_scanned': cs, 'calls_ingested': ci,
            'result_html': self._render(ms, mi, cs, ci),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _render(self, ms, mi, cs, ci):
        prefix = '<b>DRY RUN — no writes</b><br/>' if self.dry_run else ''
        return (f'{prefix}<table class="table table-sm">'
                f'<tr><th></th><th>Scanned</th><th>Ingested</th></tr>'
                f'<tr><td>Messages</td><td>{ms}</td><td>{mi}</td></tr>'
                f'<tr><td>Calls</td><td>{cs}</td><td>{ci}</td></tr>'
                f'</table>')
