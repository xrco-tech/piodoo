# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api
from odoo.exceptions import UserError

from ..models.whatsapp_rate import CATEGORY_SELECTION

_logger = logging.getLogger(__name__)


class WhatsappBillingBackfill(models.TransientModel):
    _name = 'whatsapp.billing.backfill'
    _description = 'Replay historical whatsapp.message / whatsapp.call.log into the billing ledger'

    months = fields.Integer(string='Backfill last N months', default=3, required=True,
        help='Look back this many months from today. Set 0 for "all history".')
    account_ids = fields.Many2many('comm.whatsapp.account',
        string='Accounts',
        help='Restrict to these WABA accounts. Leave empty for ALL accounts.')
    include_messages = fields.Boolean(default=True)
    include_calls = fields.Boolean(default=True)
    category_filter = fields.Selection(
        [('all', 'All categories')] + CATEGORY_SELECTION,
        default='all', required=True,
        help='Filter template messages by pricing category (all = no filter).')
    only_missing = fields.Boolean(default=True,
        help='Skip source records already in the ledger. Turn off only if you '
             'need to re-price after changing a rate card.')
    dry_run = fields.Boolean(default=True,
        help='Count what would be ingested without writing to the ledger.')

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
            # Meta category strings roughly line up with ours; also accept synonyms
            synonyms = {
                'marketing':          ['marketing'],
                'utility':            ['utility'],
                'authentication':     ['authentication'],
                'auth_international': ['authentication_international'],
                'service':            ['service', 'user_initiated', 'referral_conversion'],
                'call_minute':        [],
                'mba_token':          [],
            }
            wanted = synonyms.get(self.category_filter, [])
            if wanted:
                domain.append(('pricing_category', 'in', wanted))
            else:
                # No message-level source for these categories
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
        BillingEvent = self.env['whatsapp.billing.event']
        msgs_scanned = msgs_ingested = 0
        calls_scanned = calls_ingested = 0

        if self.include_messages:
            messages = self.env['whatsapp.message'].search(self._message_domain())
            msgs_scanned = len(messages)
            for msg in messages:
                if self.only_missing and BillingEvent.search_count([
                    ('source_model', '=', 'whatsapp.message'),
                    ('source_id', '=', msg.id),
                ]):
                    continue
                if self.dry_run:
                    msgs_ingested += 1
                    continue
                try:
                    ev = BillingEvent._create_from_message(msg)
                    if ev:
                        msgs_ingested += 1
                except Exception as e:
                    _logger.warning('Backfill msg %s failed: %s', msg.id, e)

        if self.include_calls and self.category_filter in ('all', 'call_minute'):
            calls = self.env['whatsapp.call.log'].search(self._call_domain())
            calls_scanned = len(calls)
            for call in calls:
                if self.only_missing and BillingEvent.search_count([
                    ('source_model', '=', 'whatsapp.call.log'),
                    ('source_id', '=', call.id),
                ]):
                    continue
                if self.dry_run:
                    calls_ingested += 1
                    continue
                try:
                    ev = BillingEvent._create_from_call(call)
                    if ev:
                        calls_ingested += 1
                except Exception as e:
                    _logger.warning('Backfill call %s failed: %s', call.id, e)

        self.write({
            'messages_scanned': msgs_scanned,
            'messages_ingested': msgs_ingested,
            'calls_scanned': calls_scanned,
            'calls_ingested': calls_ingested,
            'result_html': self._render_result(msgs_scanned, msgs_ingested,
                                               calls_scanned, calls_ingested),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _render_result(self, ms, mi, cs, ci):
        prefix = '<b>DRY RUN — no writes</b><br/>' if self.dry_run else ''
        return (f'{prefix}'
                f'<table class="table table-sm">'
                f'<tr><th></th><th>Scanned</th><th>Ingested</th></tr>'
                f'<tr><td>Messages</td><td>{ms}</td><td>{mi}</td></tr>'
                f'<tr><td>Calls</td><td>{cs}</td><td>{ci}</td></tr>'
                f'</table>')
