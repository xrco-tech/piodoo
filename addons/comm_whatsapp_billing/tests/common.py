# -*- coding: utf-8 -*-
"""Shared test fixtures for comm_whatsapp_billing."""
from datetime import date, datetime
from odoo.tests.common import TransactionCase


class BillingTestCase(TransactionCase):
    """Base class that gives every test a ZA country handle, a WABA account,
    and quick accessors to the three seeded rate cards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ZA = cls.env.ref('base.za')
        cls.USD = cls.env.ref('base.USD', raise_if_not_found=False)
        cls.card_2025 = cls.env.ref('comm_whatsapp_billing.rate_card_2025_jul')
        cls.card_2026aug = cls.env.ref('comm_whatsapp_billing.rate_card_2026_aug')
        cls.card_2026oct = cls.env.ref('comm_whatsapp_billing.rate_card_2026_oct')
        cls.account = cls.env['comm.whatsapp.account'].create({
            'name': 'Test WABA',
            'country_id': cls.ZA.id,
            'billing_currency_id': cls.USD.id if cls.USD else False,
        })

    def _make_message(self, wa_id='27831112222', pricing_category='marketing',
                      status='delivered', is_incoming=False, at=None):
        """Create a whatsapp.message. Note: pricing_category/status are set on
        create, so the billing hook fires immediately (mimics a fast webhook)."""
        at = at or datetime.now()
        return self.env['whatsapp.message'].create({
            'message_id': f'wamid.test-{wa_id}-{at.timestamp()}',
            'wa_id': wa_id,
            'phone_number': wa_id,
            'message_type': 'template',
            'message_timestamp': at,
            'account_id': self.account.id,
            'is_incoming': is_incoming,
            'status': 'received' if is_incoming else 'processed',
            'pricing_category': pricing_category,
            'message_status': status,
            'status_timestamp': at,
        })
