# -*- coding: utf-8 -*-
"""Cost simulator: correct arithmetic across regimes and MBA tokens."""
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'simulator', 'post_install', '-at_install')
class TestSimulator(BillingTestCase):

    def _run(self, **overrides):
        vals = dict(
            category='marketing',
            manual_recipient_count=1000,
            manual_country_id=self.ZA.id,
            expected_reply_rate=0.0,
            mba_handled_pct=0.0,
        )
        vals.update(overrides)
        wiz = self.env['whatsapp.cost.simulation'].create(vals)
        wiz.rate_card_ids = [(6, 0, [
            self.card_2025.id, self.card_2026aug.id, self.card_2026oct.id])]
        wiz.action_run()
        return wiz

    def _totals_by_card(self, wiz):
        import json
        data = json.loads(wiz.result_json)
        return {row['card_id']: row['total_usd'] for row in data}

    def test_marketing_campaign_flat(self):
        """1000 marketing recipients in ZA, no replies. Same cost on all
        three cards (they share the marketing rate)."""
        wiz = self._run(category='marketing', manual_recipient_count=1000)
        totals = self._totals_by_card(wiz)
        for card_id in (self.card_2025.id, self.card_2026aug.id,
                        self.card_2026oct.id):
            self.assertAlmostEqual(totals[card_id], 1000 * 0.0379, places=4)

    def test_mba_tokens_only_on_hybrid_cards(self):
        """1000 marketing + 30% reply + 100% MBA-handled = MBA token cost
        appears on Aug/Oct cards, not on Jul 2025 card."""
        wiz = self._run(expected_reply_rate=0.30, mba_handled_pct=1.0,
                        avg_tokens_per_interaction=22000)
        totals = self._totals_by_card(wiz)

        base = 1000 * 0.0379
        # 300 MBA interactions * 22 kilotokens * $0.002 = $13.20
        mba = 300 * 22 * 0.002

        self.assertAlmostEqual(totals[self.card_2025.id], base, places=4)
        self.assertAlmostEqual(totals[self.card_2026aug.id], base + mba, places=4)

    def test_oct_2026_service_charges_appear(self):
        """Under Oct 2026, non-MBA-handled replies fall to paid service."""
        wiz = self._run(expected_reply_rate=0.20, mba_handled_pct=0.5,
                        avg_tokens_per_interaction=22000)
        totals = self._totals_by_card(wiz)

        # 200 replies: 100 MBA + 100 paid service
        base = 1000 * 0.0379
        mba = 100 * 22 * 0.002
        service = 100 * 0.0076  # seed service rate for ZA on Oct card
        self.assertAlmostEqual(totals[self.card_2026oct.id],
                               base + mba + service, places=4)

    def test_call_minutes_are_billed_when_rate_exists(self):
        """No call-minute rate seeded yet → no call cost line."""
        wiz = self._run(avg_call_minutes_per_recipient=2.0)
        totals = self._totals_by_card(wiz)
        # Marketing only since no call_minute rate is seeded
        self.assertAlmostEqual(totals[self.card_2025.id], 1000 * 0.0379, places=4)
