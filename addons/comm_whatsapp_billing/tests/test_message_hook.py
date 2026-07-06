# -*- coding: utf-8 -*-
"""Hooks on whatsapp.message: creates a ledger row when pricing_category
arrives, is idempotent, and picks up updates on write."""
from datetime import datetime
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'hooks', 'post_install', '-at_install')
class TestMessageHook(BillingTestCase):

    def test_message_creates_billing_event(self):
        msg = self._make_message(pricing_category='marketing',
                                 at=datetime(2025, 12, 1, 10, 0))
        self.assertEqual(len(msg.billing_event_ids), 1)
        ev = msg.billing_event_ids
        self.assertEqual(ev.category, 'marketing')
        self.assertAlmostEqual(ev.price_usd, 0.0379, places=4)
        self.assertEqual(ev.country_id, self.ZA)

    def test_message_hook_is_idempotent(self):
        """Multiple writes triggering the hook should not create duplicate rows."""
        msg = self._make_message(pricing_category='marketing',
                                 at=datetime(2025, 12, 1, 10, 0))
        # Simulate a second webhook flipping status delivered → read
        msg.write({'message_status': 'read'})
        msg.write({'message_status': 'read'})
        self.assertEqual(len(msg.billing_event_ids), 1)

    def test_incoming_message_does_not_bill(self):
        """Inbound messages don't get billed — they open a CS window instead."""
        msg = self._make_message(is_incoming=True, pricing_category=False,
                                 at=datetime(2025, 12, 1, 10, 0))
        self.assertFalse(msg.billing_event_ids)
        # But the CS window should be open
        FreeWindow = self.env['whatsapp.free.window']
        self.assertTrue(FreeWindow.covers(
            self.account, msg.wa_id,
            datetime(2025, 12, 1, 11, 0), 'cs_24h'))

    def test_meta_category_synonyms_map_correctly(self):
        """Meta ships 'authentication_international' → we map to 'auth_international'."""
        msg = self._make_message(pricing_category='authentication_international',
                                 at=datetime(2025, 12, 1, 10, 0))
        self.assertEqual(msg.billing_event_ids.category, 'auth_international')
        self.assertAlmostEqual(msg.billing_event_ids.price_usd, 0.02, places=4)

    def test_unknown_category_is_skipped_gracefully(self):
        msg = self._make_message(pricing_category='some_new_meta_category',
                                 at=datetime(2025, 12, 1, 10, 0))
        self.assertFalse(msg.billing_event_ids)

    def test_utility_message_free_when_incoming_first(self):
        """Sequence: inbound opens window → outbound utility inside window is free."""
        at = datetime(2025, 12, 1, 10, 0)
        self._make_message(is_incoming=True, pricing_category=False, at=at)
        outbound = self._make_message(pricing_category='utility',
                                      status='delivered',
                                      at=at.replace(hour=11))
        ev = outbound.billing_event_ids
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev.is_free)
        self.assertEqual(ev.price_usd, 0.0)
