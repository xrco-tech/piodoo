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
