# -*- coding: utf-8 -*-
"""Free-window handling: 24h CS window, 72h entry point, and how the
Oct 2026 regime removes the service-message exemption."""
from datetime import datetime, timedelta
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'free_windows', 'post_install', '-at_install')
class TestFreeWindows(BillingTestCase):

    def _price(self, category, event_date, wa_id='27831112222'):
        vals = {
            'event_date': event_date,
            'account_id': self.account.id,
            'wa_id': wa_id,
            'category': category,
            'unit': 'message',
            'unit_qty': 1.0,
            'country_id': self.ZA.id,
        }
        self.env['whatsapp.billing.event']._price(vals)
        return vals

    def test_service_free_inside_cs_window_jul_2025(self):
        """User messages us → 24h CS window opens → service reply is free."""
        opened = datetime(2025, 12, 1, 10, 0)
        self.env['whatsapp.free.window'].open_window(
            account=self.account, wa_id='27831112222',
            window_type='cs_24h', opened_at=opened,
        )
        vals = self._price('service', opened + timedelta(hours=1))
        self.assertTrue(vals['is_free'])
        self.assertEqual(vals['price_usd'], 0.0)
        self.assertEqual(vals['free_reason'], 'cs_24h/service')

    def test_service_paid_inside_cs_window_oct_2026(self):
        """Same window, but Oct 2026 regime: service loses the exemption."""
        opened = datetime(2026, 11, 1, 10, 0)
        self.env['whatsapp.free.window'].open_window(
            account=self.account, wa_id='27831112222',
            window_type='cs_24h', opened_at=opened,
        )
        vals = self._price('service', opened + timedelta(hours=1))
        self.assertFalse(vals['is_free'])
        self.assertGreater(vals['price_usd'], 0.0)

    def test_utility_still_free_inside_cs_window_oct_2026(self):
        """Utility keeps its exemption even in Oct 2026 regime."""
        opened = datetime(2026, 11, 1, 10, 0)
        self.env['whatsapp.free.window'].open_window(
            account=self.account, wa_id='27831112222',
            window_type='cs_24h', opened_at=opened,
        )
        vals = self._price('utility', opened + timedelta(hours=1))
        self.assertTrue(vals['is_free'])
        self.assertEqual(vals['price_usd'], 0.0)

    def test_window_expires(self):
        opened = datetime(2025, 12, 1, 10, 0)
        self.env['whatsapp.free.window'].open_window(
            account=self.account, wa_id='27831112222',
            window_type='cs_24h', opened_at=opened,
        )
        # 25 hours later — CS window has closed
        vals = self._price('service', opened + timedelta(hours=25))
        self.assertFalse(vals['is_free'])

    def test_open_window_idempotent(self):
        """Opening the same window twice should extend, not duplicate."""
        FreeWindow = self.env['whatsapp.free.window']
        opened = datetime(2025, 12, 1, 10, 0)
        w1 = FreeWindow.open_window(account=self.account, wa_id='27831112222',
                                    opened_at=opened)
        w2 = FreeWindow.open_window(account=self.account, wa_id='27831112222',
                                    opened_at=opened + timedelta(hours=1))
        self.assertEqual(w1.id, w2.id)
        self.assertEqual(w2.expires_at, opened + timedelta(hours=25))

    def test_entry_72h_covers_marketing(self):
        """Free entry point applies to all categories including marketing."""
        opened = datetime(2025, 12, 1, 10, 0)
        self.env['whatsapp.free.window'].open_window(
            account=self.account, wa_id='27831112222',
            window_type='entry_72h', opened_at=opened,
        )
        vals = self._price('marketing', opened + timedelta(hours=48))
        self.assertTrue(vals['is_free'])
        self.assertEqual(vals['free_reason'], 'entry_72h')
