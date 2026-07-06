# -*- coding: utf-8 -*-
"""Backfill wizard: honours N-months + account + category filters and is
idempotent so re-running never produces duplicate ledger rows."""
from datetime import datetime, timedelta
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'backfill', 'post_install', '-at_install')
class TestBackfill(BillingTestCase):

    def _seed_messages(self, n, category='marketing', days_ago=10):
        """Create N messages WITHOUT triggering the hook — mimics
        pre-existing history from before the module was installed."""
        BillingEvent = self.env['whatsapp.billing.event']
        Msg = self.env['whatsapp.message']
        now = datetime.now()
        msgs = self.env['whatsapp.message']
        for i in range(n):
            msg = Msg.create({
                'message_id': f'backfill-{category}-{i}-{now.timestamp()}',
                'wa_id': f'2783111{i:04d}',
                'phone_number': f'2783111{i:04d}',
                'message_type': 'template',
                'message_timestamp': now - timedelta(days=days_ago),
                'account_id': self.account.id,
                'is_incoming': False,
                'status': 'processed',
                'pricing_category': category,
                'message_status': 'delivered',
                'status_timestamp': now - timedelta(days=days_ago),
            })
            msgs |= msg
        # The hook did fire on create — reset ledger to simulate history without it
        BillingEvent.search([
            ('source_model', '=', 'whatsapp.message'),
            ('source_id', 'in', msgs.ids),
        ]).unlink()
        return msgs

    def test_dry_run_writes_nothing(self):
        self._seed_messages(5)
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 1, 'dry_run': True, 'only_missing': True,
        })
        wiz.action_run()
        self.assertEqual(wiz.messages_scanned, 5)
        self.assertEqual(wiz.messages_ingested, 5)
        self.assertFalse(self.env['whatsapp.billing.event'].search([]))

    def test_real_run_ingests_and_prices(self):
        self._seed_messages(5, category='marketing')
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 1, 'dry_run': False, 'only_missing': True,
        })
        wiz.action_run()
        events = self.env['whatsapp.billing.event'].search([])
        self.assertEqual(len(events), 5)
        for ev in events:
            self.assertAlmostEqual(ev.price_usd, 0.0379, places=4)

    def test_idempotent_when_only_missing(self):
        self._seed_messages(3)
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 1, 'dry_run': False, 'only_missing': True,
        })
        wiz.action_run()
        wiz2 = wiz.copy()
        wiz2.action_run()
        # Second run should scan the same 3 but ingest 0
        self.assertEqual(wiz2.messages_scanned, 3)
        self.assertEqual(wiz2.messages_ingested, 0)
        self.assertEqual(
            self.env['whatsapp.billing.event'].search_count([]), 3)

    def test_account_filter_scopes_ingestion(self):
        other = self.env['comm.whatsapp.account'].create({
            'name': 'Second WABA', 'country_id': self.ZA.id,
        })
        self._seed_messages(2, category='marketing')  # under self.account
        # 2 more under `other`
        BillingEvent = self.env['whatsapp.billing.event']
        Msg = self.env['whatsapp.message']
        now = datetime.now()
        for i in range(2):
            m = Msg.create({
                'message_id': f'other-{i}-{now.timestamp()}',
                'wa_id': f'2784444{i:04d}',
                'phone_number': f'2784444{i:04d}',
                'message_type': 'template',
                'message_timestamp': now - timedelta(days=5),
                'account_id': other.id,
                'is_incoming': False,
                'status': 'processed',
                'pricing_category': 'marketing',
                'message_status': 'delivered',
                'status_timestamp': now - timedelta(days=5),
            })
            BillingEvent.search([('source_model', '=', 'whatsapp.message'),
                                 ('source_id', '=', m.id)]).unlink()

        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 1, 'dry_run': False, 'only_missing': True,
            'account_ids': [(6, 0, [self.account.id])],
        })
        wiz.action_run()
        # Only 2 (self.account) should be ingested
        self.assertEqual(wiz.messages_ingested, 2)

    def test_category_filter_scopes_ingestion(self):
        self._seed_messages(3, category='marketing')
        self._seed_messages(2, category='utility')
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 1, 'dry_run': False, 'only_missing': True,
            'category_filter': 'utility',
        })
        wiz.action_run()
        self.assertEqual(wiz.messages_ingested, 2)

    def test_months_cutoff(self):
        self._seed_messages(2, days_ago=5)     # inside
        self._seed_messages(3, days_ago=120)   # outside a 3-month window
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 3, 'dry_run': False, 'only_missing': True,
        })
        wiz.action_run()
        self.assertEqual(wiz.messages_ingested, 2)

    def test_months_zero_means_all(self):
        self._seed_messages(2, days_ago=5)
        self._seed_messages(3, days_ago=400)
        wiz = self.env['whatsapp.billing.backfill'].create({
            'months': 0, 'dry_run': False, 'only_missing': True,
        })
        wiz.action_run()
        self.assertEqual(wiz.messages_ingested, 5)
