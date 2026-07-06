# -*- coding: utf-8 -*-
"""MSISDN → res.country lookup uses phonenumbers correctly."""
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'country_lookup', 'post_install', '-at_install')
class TestCountryLookup(BillingTestCase):

    def test_za_number_resolves_to_za(self):
        c = self.env['whatsapp.billing.event']._country_from_wa_id('27831234567')
        self.assertEqual(c, self.ZA)

    def test_leading_plus_is_tolerated(self):
        c = self.env['whatsapp.billing.event']._country_from_wa_id('+27831234567')
        self.assertEqual(c, self.ZA)

    def test_invalid_number_returns_empty(self):
        c = self.env['whatsapp.billing.event']._country_from_wa_id('not-a-number')
        self.assertFalse(c)

    def test_empty_returns_empty(self):
        c = self.env['whatsapp.billing.event']._country_from_wa_id('')
        self.assertFalse(c)

    def test_country_autofilled_on_event_create(self):
        ev = self.env['whatsapp.billing.event'].create({
            'account_id': self.account.id,
            'wa_id': '27831234567',
            'category': 'marketing',
            'unit': 'message',
            'unit_qty': 1.0,
        })
        self.assertEqual(ev.country_id, self.ZA)
