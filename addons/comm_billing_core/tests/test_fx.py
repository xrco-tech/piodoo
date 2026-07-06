# -*- coding: utf-8 -*-
"""FX resolution: provider monthly override → Odoo rate → USD fallback."""
from datetime import date, datetime
from odoo.tests import tagged, common


@tagged('comm_billing', 'fx', 'post_install', '-at_install')
class TestFx(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.ZAR = self.env['res.currency'].search([('name', '=', 'ZAR')], limit=1)

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
