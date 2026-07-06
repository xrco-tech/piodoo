# -*- coding: utf-8 -*-
"""Rate resolution: right card active on right date, right rate per category,
correct behaviour across the Jul 2025 / Aug 2026 / Oct 2026 regime changes."""
from datetime import date
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'rates', 'post_install', '-at_install')
class TestRateResolution(BillingTestCase):

    def test_active_card_by_date(self):
        RateCard = self.env['whatsapp.rate.card']
        self.assertEqual(RateCard.active_on(date(2025, 12, 1)), self.card_2025)
        self.assertEqual(RateCard.active_on(date(2026, 8, 15)), self.card_2026aug)
        self.assertEqual(RateCard.active_on(date(2026, 11, 1)), self.card_2026oct)

    def test_za_rates_match_seed(self):
        rate = self.card_2025.resolve_rate(self.ZA, 'marketing')
        self.assertAlmostEqual(rate.price_usd, 0.0379, places=4)

        rate = self.card_2025.resolve_rate(self.ZA, 'utility')
        self.assertAlmostEqual(rate.price_usd, 0.0076, places=4)

        rate = self.card_2025.resolve_rate(self.ZA, 'authentication')
        self.assertAlmostEqual(rate.price_usd, 0.0076, places=4)

        rate = self.card_2025.resolve_rate(self.ZA, 'auth_international')
        self.assertAlmostEqual(rate.price_usd, 0.02, places=4)

    def test_mba_token_only_on_hybrid_cards(self):
        self.assertFalse(self.card_2025.resolve_rate(None, 'mba_token'))
        aug = self.card_2026aug.resolve_rate(None, 'mba_token')
        self.assertTrue(aug)
        self.assertAlmostEqual(aug.price_usd, 0.002, places=4)
        oct_ = self.card_2026oct.resolve_rate(None, 'mba_token')
        self.assertAlmostEqual(oct_.price_usd, 0.002, places=4)

    def test_service_rate_by_regime(self):
        """Service is free (via flag) on Jul 2025 & Aug 2026, paid on Oct 2026."""
        self.assertTrue(self.card_2025.service_free_in_cs_window)
        self.assertTrue(self.card_2026aug.service_free_in_cs_window)
        self.assertFalse(self.card_2026oct.service_free_in_cs_window)

        # Oct 2026 has a non-zero service rate seeded
        rate = self.card_2026oct.resolve_rate(self.ZA, 'service')
        self.assertTrue(rate)
        self.assertGreater(rate.price_usd, 0)

    def test_global_fallback_for_country_null_rate(self):
        """MBA tokens have no country row. Resolver should return the global
        row when asked for a specific country."""
        rate = self.card_2026aug.resolve_rate(self.ZA, 'mba_token')
        self.assertTrue(rate)
        self.assertFalse(rate.country_id)

    def test_no_active_card_returns_empty(self):
        RateCard = self.env['whatsapp.rate.card']
        # Deactivate all cards, look up
        RateCard.search([]).write({'active': False})
        self.assertFalse(RateCard.active_on(date(2026, 8, 15)))
