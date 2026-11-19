# -*- coding: utf-8 -*-
"""FX resolution: provider monthly override → Odoo rate → USD fallback."""
from datetime import date, datetime
from odoo.tests import tagged, common


@tagged('comm_billing', 'fx', 'post_install', '-at_install')
class TestFx(common.TransactionCase):

    def setUp(self):
        super().setUp()
        # ZAR is inactive on a database with no South African company yet.
        self.ZAR = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'ZAR')], limit=1)

    def test_provider_specific_wins(self):
        self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id,
            'provider': 'Meta', 'rate': 18.0,
        })
        self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id,
            'provider': False, 'rate': 20.0,
        })
        fx, cur = self.env['comm.billing.event']._resolve_fx(
            'Meta', datetime(2026, 6, 15), currency_hint=self.ZAR)
        self.assertAlmostEqual(fx, 18.0, places=2)

    def test_house_wide_fallback(self):
        self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id,
            'provider': False, 'rate': 20.0,
        })
        fx, _ = self.env['comm.billing.event']._resolve_fx(
            'Infobip', datetime(2026, 6, 15), currency_hint=self.ZAR)
        self.assertAlmostEqual(fx, 20.0, places=2)

    def test_no_rate_returns_usd(self):
        fx, cur = self.env['comm.billing.event']._resolve_fx(
            'Nowhere', datetime(2026, 6, 15), currency_hint=self.ZAR)
        self.assertEqual(fx, 1.0)
        self.assertEqual(cur.name, 'USD')

    def test_stale_odoo_rate_is_not_used(self):
        """The 2010 sample rate Odoo ships must not price a 2026 charge."""
        self.ZAR.active = True
        Rate = self.env['res.currency.rate']
        Rate.search([('currency_id', '=', self.ZAR.id)]).unlink()
        Rate.create({'currency_id': self.ZAR.id, 'name': date(2010, 1, 1), 'rate': 10.5618,
                     'company_id': self.env.company.id})
        fx, cur = self.env['comm.billing.event']._resolve_fx(
            'Meta', datetime(2026, 6, 15), currency_hint=self.ZAR)
        self.assertEqual((fx, cur.name), (1.0, 'USD'))
        Rate.create({'currency_id': self.ZAR.id, 'name': date(2026, 6, 1), 'rate': 16.4,
                     'company_id': self.env.company.id})
        fx, cur = self.env['comm.billing.event']._resolve_fx(
            'Meta', datetime(2026, 6, 15), currency_hint=self.ZAR)
        self.assertEqual(cur, self.ZAR)
        self.assertGreater(fx, 1.0)

    def test_entering_a_rate_reconverts_recorded_charges(self):
        self.ZAR.active = True
        self.env.company.currency_id = self.ZAR
        self.env['res.currency.rate'].search([('currency_id', '=', self.ZAR.id)]).unlink()
        Event = self.env['comm.billing.event']
        usd = self.env.ref('base.USD')

        def charge(n, provider, when):
            event = Event.create({'event_date': when, 'channel': 'whatsapp', 'category': 'marketing',
                                  'provider': provider, 'source_model': 'fxtest', 'source_id': n})
            event.write({'price_usd': 2.0, 'price_local': 2.0, 'fx_rate': 1.0, 'currency_id': usd.id})
            return event

        june_meta = charge(1, 'Meta', datetime(2026, 6, 15))
        june_sms = charge(2, 'Infobip', datetime(2026, 6, 20))
        july_meta = charge(3, 'Meta', datetime(2026, 7, 2))
        may_meta = charge(4, 'Meta', datetime(2026, 5, 30))

        house = self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id, 'rate': 16.0, 'source': 'manual'})
        self.assertAlmostEqual(june_meta.price_local, 32.0)
        self.assertAlmostEqual(june_sms.price_local, 32.0)
        self.assertAlmostEqual(july_meta.price_local, 32.0, msg='the last rate carries forward')
        self.assertEqual(june_meta.currency_id, self.ZAR)
        self.assertEqual(may_meta.currency_id, usd, 'earlier months are untouched')

        self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id, 'provider': 'Meta', 'rate': 18.0})
        self.assertAlmostEqual(june_meta.price_local, 36.0)
        self.assertAlmostEqual(june_sms.price_local, 32.0)

        house.rate = 17.0
        self.assertAlmostEqual(june_sms.price_local, 34.0)
        self.assertAlmostEqual(june_meta.price_local, 36.0)

    def _fixed_rand_rate(self, code='*120*777#', price=0.5, seconds=20, carrier=False, card=None):
        """A card for one dialled code, priced in rand per block of seconds."""
        card = card or self.env['comm.billing.rate.card'].create({
            'name': 'Fixed rand USSD %s' % code, 'channel': 'ussd', 'provider': 'Fixed Rand Test',
            'service_code': code,
            'effective_from': date(2026, 1, 1), 'billing_model': 'per_session',
        })
        return self.env['comm.billing.rate'].create({
            'card_id': card.id, 'category': 'ussd_session', 'direction': 'any',
            'unit': 'block', 'block_seconds': seconds, 'price_usd': 0.0, 'carrier': carrier,
            'price_local': price, 'local_currency_id': self.ZAR.id,
        })

    def _fixed_rand_event(self, blocks, code='*120*777#', carrier=False):
        """A session long enough to be charged as `blocks` blocks of 20 s."""
        self._seq = getattr(self, '_seq', 0) + 1
        return self.env['comm.billing.event'].create({
            'event_date': datetime(2026, 6, 15), 'channel': 'ussd', 'provider': 'Fixed Rand Test',
            'category': 'ussd_session', 'unit': 'block', 'unit_qty': 1.0,
            'duration_seconds': blocks * 20 - 5, 'service_code': code, 'carrier': carrier,
            'source_model': 'test.fixed.rand', 'source_id': self._seq,
        })

    def test_blocks_of_seconds(self):
        blocks = self.env['comm.billing.event']._blocks
        self.assertEqual([blocks(s) for s in (0, None, 1, 20, 20.5, 45, 60, 61)],
                         [1, 1, 1, 1, 2, 3, 3, 4])
        self.assertEqual([blocks(s, 22) for s in (21, 22, 23, 44, 45)], [1, 1, 2, 2, 3])

    def test_a_card_for_one_code_prices_only_that_code(self):
        Card = self.env['comm.billing.rate.card']
        Card.search([('channel', '=', 'ussd')]).active = False
        rate = self._fixed_rand_rate()
        mine = self._fixed_rand_event(3)
        self.assertEqual((mine.rate_id, mine.unit_qty), (rate, 3))
        self.assertAlmostEqual(mine.price_local, 1.5, places=4)
        # Another code, or no code at all, is not charged from this card.
        for code in ('*120*999#', False):
            other = self._fixed_rand_event(3, code=code)
            self.assertFalse(other.rate_card_id)
            self.assertEqual((other.price_local, other.price_usd), (0.0, 0.0))
        # A second provider's code has its own price and its own block length,
        # longer on one network.
        cheap = self._fixed_rand_rate(code='*120*888#', price=0.07)
        mtn = self._fixed_rand_rate(price=0.07, seconds=22, carrier='MTN', card=cheap.card_id)
        usual = self.env['comm.billing.event'].create({
            'event_date': datetime(2026, 6, 15), 'channel': 'ussd', 'category': 'ussd_session',
            'unit': 'block', 'duration_seconds': 21, 'service_code': '*120*888#',
            'source_model': 'test.fixed.rand', 'source_id': 901,
        })
        on_mtn = self.env['comm.billing.event'].create({
            'event_date': datetime(2026, 6, 15), 'channel': 'ussd', 'category': 'ussd_session',
            'unit': 'block', 'duration_seconds': 21, 'service_code': '*120*888#', 'carrier': 'MTN',
            'source_model': 'test.fixed.rand', 'source_id': 902,
        })
        self.assertEqual((usual.rate_id, usual.unit_qty), (cheap, 2))
        self.assertEqual((on_mtn.rate_id, on_mtn.unit_qty), (mtn, 1))
        self.assertAlmostEqual(usual.price_local, 0.14, places=4)
        self.assertAlmostEqual(on_mtn.price_local, 0.07, places=4)

    def test_price_fixed_in_rand_stands_whatever_the_rate(self):
        rate = self._fixed_rand_rate()
        # No exchange rate yet: the rand amount is still right, dollars unknown.
        event = self._fixed_rand_event(3)
        self.assertEqual(event.rate_id, rate)
        self.assertAlmostEqual(event.price_local, 1.5, places=4)
        self.assertEqual(event.currency_id, self.ZAR)
        self.assertEqual(event.price_usd, 0.0)
        # The month's rate arrives: rand is unchanged, dollars follow.
        self.env['comm.billing.fx.rate'].create({
            'date': date(2026, 6, 1), 'currency_id': self.ZAR.id, 'provider': False, 'rate': 20.0,
        })
        event._reconvert()
        self.assertAlmostEqual(event.price_local, 1.5, places=4)
        self.assertAlmostEqual(event.price_usd, 0.075, places=6)
        later = self._fixed_rand_event(2)
        self.assertAlmostEqual(later.price_local, 1.0, places=4)
        self.assertAlmostEqual(later.price_usd, 0.05, places=6)

    def test_fee_per_session_on_top_of_time(self):
        """7c for the session plus 21c for every started 20 seconds."""
        self.ZAR.active = True
        card = self.env['comm.billing.rate.card'].create({
            'name': 'Fee test', 'channel': 'ussd', 'provider': 'Fee Test',
            'service_code': '*134*0000#', 'effective_from': date(2026, 1, 1),
            'billing_model': 'per_session',
            'rate_ids': [(0, 0, {
                'category': 'ussd_session', 'unit': 'block', 'price_usd': 0.0,
                'block_seconds': 20, 'price_local': 0.21, 'session_fee_local': 0.07,
                'local_currency_id': self.ZAR.id,
            })],
        })
        Event = self.env['comm.billing.event']
        charge = lambda seconds, code='*134*0000#': Event.create({
            'channel': 'ussd', 'provider': 'Fee Test', 'category': 'ussd_session',
            'unit': 'block', 'unit_qty': 1.0, 'duration_seconds': seconds,
            'service_code': code, 'event_date': datetime(2026, 6, 15),
        })
        short, minute = charge(5), charge(60)
        self.assertEqual(short.rate_card_id, card)
        self.assertAlmostEqual(short.price_local, 0.28, places=4)
        self.assertAlmostEqual(minute.price_local, 0.70, places=4)
        self.assertEqual(minute.unit_qty, 3)
        self.assertEqual(minute.currency_id, self.ZAR)
        self.assertNotEqual(charge(60, '*134*9999#').rate_card_id, card,
                            'another code is not priced from this list')
