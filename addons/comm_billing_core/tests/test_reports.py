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
