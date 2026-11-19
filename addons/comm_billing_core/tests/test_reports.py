# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBillingReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = 'UTC'
        cls.Report = cls.env['comm.billing.report']
        cls.Event = cls.env['comm.billing.event']
        cls.currency = cls.env.company.currency_id
        cls.Event.search([]).unlink()
        cls.env['comm.billing.budget'].search([]).unlink()
        cls.env['comm.billing.fee'].search([]).unlink()
        cls.today = cls.Report._today()
        cls.first = cls.today.replace(day=1)
        cls.seq = 0

    @classmethod
    def _event(cls, day, cost, channel='whatsapp', category='marketing', **extra):
        """A priced ledger row; the pricing engine is bypassed on purpose."""
        cls.seq += 1
        event = cls.Event.create(dict({
            'event_date': datetime.combine(day, time(12, 0)),
            'channel': channel, 'category': category, 'provider': 'Meta',
            'source_model': 'test', 'source_id': cls.seq,
        }, **extra))
        event.write({'price_local': cost, 'price_usd': cost / 10.0,
                     'currency_id': cls.currency.id, 'fx_rate': 10.0})
        return event

    def test_overview_totals_and_comparison(self):
        self._event(self.first, 100.0)
        self._event(self.first, 50.0, channel='sms', category='sms_outbound_domestic',
                    provider='Infobip')
        self._event(self.first - relativedelta(months=1), 75.0)
        data = self.Report.overview('month')
        self.assertAlmostEqual(data['spent'], 150.0)
        self.assertAlmostEqual(data['prev'], 75.0)
        self.assertEqual(data['change_pct'], 100)
        self.assertEqual([c['key'] for c in data['channels']], ['whatsapp', 'sms'])
        self.assertEqual(data['channels'][0]['share'], 67)
        self.assertEqual(data['unpriced'], 2)  # no rate matched the test rows
        self.assertAlmostEqual(sum(b['cost'] for b in data['days']['bars']), 150.0)
        self.assertIsNone(data['budget'])

    def test_group_by_and_other_currency(self):
        self._event(self.first, 100.0, campaign_id='Specials')
        self._event(self.first, 20.0)
        usd = self.env.ref('base.USD')
        other = usd if usd != self.currency else self.env.ref('base.EUR')
        self._event(self.first, 999.0).write({'currency_id': other.id})
        data = self.Report.overview('month', group_by='campaign')
        self.assertAlmostEqual(data['spent'], 120.0)
        self.assertEqual(data['unconverted'], 1)
        labels = {r['label']: r['cost'] for r in data['rows']}
        self.assertAlmostEqual(labels['Specials'], 100.0)
        self.assertAlmostEqual(labels['No campaign'], 20.0)
        for group in ('category', 'account', 'country', 'contact', 'nonsense'):
            self.assertTrue(self.Report.overview('month', group_by=group)['rows'])

    def test_periods(self):
        self._event(self.first - timedelta(days=1), 40.0)
        self.assertAlmostEqual(self.Report.overview('last_month')['spent'], 40.0)
        self.assertAlmostEqual(self.Report.overview('3m')['spent'], 40.0)
        day = str(self.first - timedelta(days=1))
        self.assertAlmostEqual(self.Report.overview('custom', day, day)['spent'], 40.0)

    def test_budget_and_warnings(self):
        budget = self.env['comm.billing.budget'].create({
            'amount': 100.0, 'limit_whatsapp': 50.0, 'warn_day': True,
            'warn_day_amount': 60.0})
        self._event(self.first, 90.0)
        block = self.Report.overview('month')['budget']
        self.assertEqual(block['pct'], 90)
        self.assertAlmostEqual(block['left'], 10.0)
        whatsapp = self.Report.overview('month')['channels'][0]
        self.assertEqual(whatsapp['limit_pct'], 180)

        budget._check_warnings()
        kinds = set(budget.alert_ids.mapped('kind'))
        self.assertIn('pct', kinds)
        self.assertIn('channel:whatsapp', kinds)
        self.assertIn('day:%s' % self.first, kinds)
        sent = len(budget.alert_ids)
        budget._check_warnings()
        self.assertEqual(len(budget.alert_ids), sent, 'each warning goes out once a month')

    def test_statement_and_invoice_check(self):
        last_month = self.first - relativedelta(months=1)
        self._event(last_month, 200.0)
        free = self._event(last_month, 0.0, category='service')
        free.write({'is_free': True})
        self.env['comm.billing.invoice'].create({
            'month': last_month + timedelta(days=3), 'provider': 'Meta', 'amount': 202.0})
        statement = self.Report.statement()
        self.assertTrue(statement['closed'])
        self.assertAlmostEqual(statement['total'], 200.0)
        self.assertEqual(statement['free_qty'], 1)
        check = statement['checks'][0]
        self.assertEqual(check['provider'], 'Meta')
        self.assertAlmostEqual(check['diff'], 2.0)
        self.assertEqual(check['result'], 'close')
        lines = statement['sections'][0]['lines']
        self.assertEqual([line['free'] for line in lines], [False, True])
        self.assertEqual(self.Report.statement('not-a-month')['month'], statement['month'])

    def test_source_filter_and_grouping(self):
        self._event(self.first, 100.0, source='chat2work')
        self._event(self.first, 30.0, source='contact_centre')
        self._event(self.first, 5.0)
        self.assertAlmostEqual(self.Report.overview('month')['spent'], 135.0)
        only = self.Report.overview('month', source='chat2work')
        self.assertAlmostEqual(only['spent'], 100.0)
        self.assertEqual(only['source'], 'chat2work')
        self.assertIsNone(only['budget'])
        self.assertAlmostEqual(self.Report.overview('month', source='other')['spent'], 5.0)
        self.assertAlmostEqual(self.Report.overview('month', source='bogus')['spent'], 135.0)
        rows = {r['label']: r['cost'] for r in self.Report.overview('month', group_by='source')['rows']}
        self.assertAlmostEqual(rows['Chat2Work'], 100.0)
        self.assertAlmostEqual(rows['Contact Centre'], 30.0)
        self.assertAlmostEqual(rows['Not attributed'], 5.0)
        found = self.Event.search(only['domain'])
        self.assertEqual(found.mapped('source'), ['chat2work'])

    def test_unknown_person_is_not_attributed(self):
        event = self._event(self.first, 1.0, wa_id='27000000001')
        self.assertEqual(event.source, 'other')

    def test_llm_usage_is_recorded(self):
        before = self.Event.search_count([])
        events = self.Event._log_llm_usage(
            'claude-haiku-4-5-20251001',
            {'input_tokens': 1500, 'output_tokens': 300, 'cache_read_input_tokens': 0},
            source='chat2work', feature='sidekick')
        self.assertEqual(len(events), 2, 'one row per kind of token that was used')
        self.assertEqual(self.Event.search_count([]), before + 2)
        self.assertEqual(set(events.mapped('category')), {'llm_input', 'llm_output'})
        self.assertEqual(set(events.mapped('carrier')), {'claude-haiku-4-5'})
        self.assertEqual(set(events.mapped('source')), {'chat2work'})
        self.assertAlmostEqual(events.filtered(lambda e: e.category == 'llm_input').unit_qty, 1.5)
        # A second call is a second charge, and bad input never raises.
        self.assertEqual(len(self.Event._log_llm_usage('m', {'input_tokens': 10}, feature='sidekick')), 1)
        self.assertFalse(self.Event._log_llm_usage('m', None))
        self.assertFalse(self.Event._log_llm_usage('m', {'input_tokens': 'lots'}))
        rows = self.Report.overview('month', group_by='source')['rows']
        self.assertIn('Chat2Work: Sidekick (AI)', [r['label'] for r in rows])

    def test_dashboard_cost(self):
        self._event(self.today, 12.0, source='chat2work')
        self._event(self.today, 3.0, source='chat2work', channel='sms', category='sms_outbound_domestic')
        self._event(self.today, 99.0, source='contact_centre')
        self._event(self.today - timedelta(days=10), 50.0, source='chat2work')
        since = self.Report._utc(self.today)
        cost = self.Report.dashboard_cost('chat2work', since)
        self.assertAlmostEqual(cost['total'], 15.0)
        self.assertEqual([c['key'] for c in cost['channels']], ['whatsapp', 'sms'])
        self.assertEqual((cost['date_from'], cost['date_to']), (str(self.today), str(self.today)))
        self.assertAlmostEqual(
            self.Report.dashboard_cost('chat2work', self.Report._utc(self.today - timedelta(days=29)))['total'], 65.0)
        self.assertFalse(self.Report.dashboard_cost('nonsense', since))
        outsider = self.env['res.users'].create({'name': 'No billing', 'login': 'nobilling'})
        self.assertFalse(self.Report.with_user(outsider).dashboard_cost('chat2work', since),
                         'people without billing access get no figure')

    def test_sender_can_name_the_feature(self):
        tagged_event = self.Event.with_context(billing_feature='job_alert').create({
            'channel': 'sms', 'category': 'sms_outbound_domestic', 'source_model': 'test', 'source_id': 9001})
        self.assertEqual(tagged_event.feature, 'job_alert')
        plain = self.Event.create({
            'channel': 'sms', 'category': 'sms_outbound_domestic', 'source_model': 'test', 'source_id': 9002})
        self.assertFalse(plain.feature)
        self._event(self.today, 4.0, source='chat2work', feature='job_alert')
        self._event(self.today, 1.5, source='chat2work', feature='sidekick', channel='other', category='llm_output')
        self._event(self.today, 7.0, source='chat2work')
        cost = self.Report.dashboard_cost('chat2work', self.Report._utc(self.today))
        self.assertEqual([(f['label'], f['cost']) for f in cost['features']],
                         [('Job alerts', 4.0), ('Sidekick (AI)', 1.5)])
        self.assertAlmostEqual(cost['total'], 12.5)

    def test_budget_warnings_for_other_apps(self):
        self.assertEqual(self.Report.budget_warnings(), [])
        budget = self.env['comm.billing.budget'].create({'amount': 100.0})
        self._event(self.first, 90.0, source='chat2work')
        budget._check_warnings()
        warnings = self.Report.budget_warnings()
        self.assertEqual(len(warnings), len(budget.alert_ids))
        self.assertIn('80%', warnings[-1]['text'])
        cost = self.Report.dashboard_cost('chat2work', self.Report._utc(self.first))
        self.assertEqual(cost['warnings'], warnings)
        # Last month's warnings are over, and outsiders get none.
        budget.alert_ids.write({'month': self.first - relativedelta(months=1)})
        self.assertEqual(self.Report.budget_warnings(), [])
        outsider = self.env['res.users'].create({'name': 'No billing 2', 'login': 'nobilling2'})
        self.assertEqual(self.Report.with_user(outsider).budget_warnings(), [])

    # ---- fixed fees ----
    def _fee(self, **vals):
        return self.env['comm.billing.fee'].create(dict({
            'name': 'USSD hosting', 'provider': 'Connect Mobile', 'channel': 'ussd',
            'source': 'chat2work', 'kind': 'monthly', 'date_from': self.first,
            'amount': 850.0, 'vat_pct': 15.0}, **vals))

    def test_monthly_fee_is_charged_every_month(self):
        start = self.first - relativedelta(months=2) + timedelta(days=9)
        fee = self._fee(date_from=start)
        self.assertEqual(len(fee.event_ids), 3, 'one charge a month, the running month included')
        self.assertEqual(set(fee.event_ids.mapped('category')), {'fixed_fee'})
        self.assertEqual(min(fee.event_ids.mapped('event_date')).date(), start)
        self.assertEqual(max(fee.event_ids.mapped('event_date')).date(), self.first)
        self.assertAlmostEqual(sum(fee.event_ids.mapped('price_local')), 2550.0)
        self.assertEqual(set(fee.event_ids.mapped('currency_id')), {self.currency})
        fee._sync()
        self.env['comm.billing.fee']._cron_post()
        self.assertEqual(len(fee.event_ids), 3, 'running it again adds nothing')

    def test_overview_counts_fixed_fees_apart_from_usage(self):
        self._event(self.first, 100.0, channel='ussd', category='ussd_session',
                    provider='Connect Mobile')
        self._fee()
        self._fee(name='USSD activation', kind='once', amount=2750.0)
        self._fee(name='Later', kind='once', amount=1.0, date_from=self.today + timedelta(days=40))
        data = self.Report.overview('month')
        self.assertAlmostEqual(data['spent'], 3700.0)
        self.assertAlmostEqual(data['usage'], 100.0)
        self.assertAlmostEqual(data['fixed'], 3600.0)
        self.assertAlmostEqual(data['vat'], 540.0)
        self.assertAlmostEqual(data['spent_vat'], 4240.0)
        self.assertEqual([(f['name'], f['cost']) for f in data['fees']],
                         [('USSD activation', 2750.0), ('USSD hosting', 850.0)])
        ussd = data['channels'][0]
        self.assertAlmostEqual(ussd['fixed'], 3600.0)
        self.assertAlmostEqual(ussd['usage'], 100.0)
        self.assertEqual(data['unpriced'], 1, 'a fixed fee is not a charge without a rate')
        self.assertAlmostEqual(sum(b['cost'] for b in data['days']['bars']), 100.0,
                               'the daily chart is usage only')
        # The forecast grows usage with the days, and adds the fixed fees once.
        self.assertGreaterEqual(data['forecast'], 3700.0 - 0.01)
        days = (self.today - self.first).days + 1
        self.assertLessEqual(data['forecast'], 3600.0 + 100.0 * 62 / max(days - 1, 0.5))
        rows = {r['label']: r['cost'] for r in data['rows']}
        self.assertAlmostEqual(rows['Fixed fees'], 3600.0)
        self.assertAlmostEqual(self.Report.overview('month', source='chat2work')['fixed'], 3600.0)
        self.assertAlmostEqual(self.Report.overview('month', source='contact_centre')['fixed'], 0.0)
        self.assertAlmostEqual(self.Report.dashboard_cost(
            'chat2work', self.Report._utc(self.first))['total'], 3600.0)

    def test_fixed_fees_count_against_the_budget(self):
        budget = self.env['comm.billing.budget'].create({
            'amount': 1000.0, 'warn_day': True, 'warn_day_amount': 60.0})
        self._fee()
        block = self.Report.overview('month')['budget']
        self.assertEqual(block['pct'], 85)
        budget._check_warnings()
        kinds = set(budget.alert_ids.mapped('kind'))
        self.assertIn('pct', kinds)
        self.assertFalse([k for k in kinds if k.startswith('day:')],
                         'a fixed fee is not an unusually expensive day')

    def test_deposit_is_held_not_spent(self):
        deposit = self._fee(name='Deposit', kind='deposit', amount=5000.0, vat_pct=0.0)
        self.assertFalse(deposit.event_ids)
        data = self.Report.overview('month')
        self.assertAlmostEqual(data['spent'], 0.0)
        self.assertAlmostEqual(data['held'], 5000.0)
        self.assertTrue(data['deposits'][0]['paid_now'])
        deposit.date_until = self.first
        self.assertAlmostEqual(self.Report.overview('month')['held'], 5000.0)
        deposit.write({'date_from': self.first - relativedelta(months=3),
                       'date_until': self.first - relativedelta(months=2)})
        self.assertFalse(self.Report.overview('month')['deposits'], 'given back: no longer held')

    def test_changing_a_fee_corrects_the_ledger(self):
        fee = self._fee(date_from=self.first - relativedelta(months=1))
        self.assertEqual(len(fee.event_ids), 2)
        fee.amount = 900.0
        self.assertEqual(set(fee.event_ids.mapped('price_local')), {900.0})
        fee.write({'provider': 'Someone Else', 'source': 'contact_centre'})
        self.assertEqual(set(fee.event_ids.mapped('provider')), {'Someone Else'})
        self.assertEqual(set(fee.event_ids.mapped('source')), {'contact_centre'})
        fee.date_until = self.first - timedelta(days=1)
        self.assertEqual(len(fee.event_ids), 1, 'ended last month: this month is not charged')
        fee.kind = 'deposit'
        self.assertFalse(fee.event_ids)
        fee.kind = 'once'
        events = fee.event_ids
        self.assertEqual(len(events), 1)
        events._reconvert()
        self.assertAlmostEqual(events.price_local, 900.0, msg='a new exchange rate leaves the fee alone')
        fee.unlink()
        self.assertFalse(events.exists())
        with self.assertRaises(Exception):
            self._fee(amount=0.0)

    def test_statement_with_fixed_fees_vat_and_deposit(self):
        last_month = self.first - relativedelta(months=1)
        card = self.env['comm.billing.rate.card'].create({
            'name': 'Connect', 'channel': 'ussd', 'provider': 'Connect Mobile',
            'effective_from': last_month, 'vat_pct': 15.0})
        usage = self._event(last_month, 100.0, channel='ussd', category='ussd_session',
                            provider='Connect Mobile')
        usage.write({'rate_card_id': card.id})
        self._event(last_month, 200.0)  # Meta: no VAT on its card
        self._fee(date_from=last_month, date_until=last_month + timedelta(days=20))
        self._fee(name='Deposit', kind='deposit', amount=5000.0, vat_pct=0.0,
                  date_from=last_month + timedelta(days=5))
        self.env['comm.billing.invoice'].create({
            'month': last_month, 'provider': 'Connect Mobile', 'amount': 5950.0})
        statement = self.Report.statement()
        self.assertAlmostEqual(statement['usage'], 300.0)
        self.assertAlmostEqual(statement['fixed'], 850.0)
        self.assertAlmostEqual(statement['total'], 1150.0)
        self.assertAlmostEqual(statement['vat'], 142.5)
        self.assertAlmostEqual(statement['total_vat'], 1292.5)
        self.assertAlmostEqual(statement['deposit_total'], 5000.0)
        self.assertAlmostEqual(statement['cash'], 6292.5)
        section = statement['sections'][0]
        self.assertEqual((section['channel'], section['provider']), ('ussd', 'Connect Mobile'))
        self.assertAlmostEqual(section['total'], 950.0)
        self.assertEqual([(line['label'], line['fixed']) for line in section['lines']],
                         [('Sessions', False), ('USSD hosting', True)])
        check = next(c for c in statement['checks'] if c['provider'] == 'Connect Mobile')
        self.assertAlmostEqual(check['ours'], 5950.0)
        self.assertAlmostEqual(check['deposit'], 5000.0)
        self.assertEqual(check['result'], 'match')
        # The PDF renders with the new lines.
        html = self.env['ir.actions.report']._render_qweb_html(
            'comm_billing_core.report_statement', [], data={'month': statement['month']})[0]
        self.assertIn(b'Cash needed this month', html)
        self.assertIn(b'Fixed: ', html)
