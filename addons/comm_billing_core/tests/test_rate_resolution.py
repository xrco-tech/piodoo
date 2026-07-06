# -*- coding: utf-8 -*-
"""Rate resolution: channel + country + category + carrier + direction + tier."""
from datetime import date, datetime
from odoo.tests import tagged, common


@tagged('comm_billing', 'rates', 'post_install', '-at_install')
class TestRateResolution(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.ZA = self.env.ref('base.za')
        self.card = self.env['comm.billing.rate.card'].create({
            'name': 'Test card', 'channel': 'sms', 'provider': 'Infobip',
            'effective_from': date(2025, 1, 1),
            'billing_model': 'per_segment',
        })

    def test_country_specific_wins_over_global(self):
        global_rate = self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'category': 'sms_outbound_domestic',
            'unit': 'segment', 'price_usd': 0.05,
        })
        za_rate = self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'country_id': self.ZA.id,
            'category': 'sms_outbound_domestic', 'unit': 'segment',
            'price_usd': 0.008,
        })
        chosen = self.card.resolve_rate(
            country=self.ZA, category='sms_outbound_domestic')
        self.assertEqual(chosen, za_rate)

    def test_active_on_by_channel(self):
        RateCard = self.env['comm.billing.rate.card']
        RateCard.create({
            'name': 'WA card', 'channel': 'whatsapp',
            'effective_from': date(2025, 1, 1),
            'billing_model': 'per_message_2025',
        })
        self.assertEqual(
            RateCard.active_on('sms', date(2025, 6, 1)), self.card)
        self.assertNotEqual(
            RateCard.active_on('whatsapp', date(2025, 6, 1)), self.card)

    def test_direction_filter(self):
        self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'country_id': self.ZA.id,
            'category': 'sms_outbound_domestic', 'direction': 'outbound',
            'unit': 'segment', 'price_usd': 0.008,
        })
        # Inbound direction should NOT match (rate is outbound-only)
        chosen = self.card.resolve_rate(
            country=self.ZA, category='sms_outbound_domestic',
            direction='inbound')
        self.assertFalse(chosen)

    def test_volume_tier(self):
        tier1 = self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'country_id': self.ZA.id,
            'category': 'sms_outbound_domestic', 'unit': 'segment',
            'price_usd': 0.008, 'tier_from': 0, 'tier_to': 1000,
        })
        tier2 = self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'country_id': self.ZA.id,
            'category': 'sms_outbound_domestic', 'unit': 'segment',
            'price_usd': 0.005, 'tier_from': 1000,
        })
        self.assertEqual(
            self.card.resolve_rate(country=self.ZA,
                                   category='sms_outbound_domestic',
                                   monthly_volume=500),
            tier1)
        self.assertEqual(
            self.card.resolve_rate(country=self.ZA,
                                   category='sms_outbound_domestic',
                                   monthly_volume=5000),
            tier2)

    def test_billing_event_lands_with_price(self):
        self.env['comm.billing.rate'].create({
            'card_id': self.card.id, 'country_id': self.ZA.id,
            'category': 'sms_outbound_domestic', 'unit': 'segment',
            'price_usd': 0.008,
        })
        ev = self.env['comm.billing.event'].create({
            'event_date': datetime(2025, 6, 1),
            'channel': 'sms', 'provider': 'Infobip',
            'wa_id': '27831234567',
            'category': 'sms_outbound_domestic',
            'unit': 'segment', 'unit_qty': 3.0,
        })
        self.assertAlmostEqual(ev.price_usd, 3.0 * 0.008, places=4)
        self.assertEqual(ev.country_id, self.ZA)
