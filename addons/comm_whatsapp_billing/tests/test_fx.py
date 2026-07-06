# -*- coding: utf-8 -*-
"""FX resolution priority: Meta monthly → Odoo rate → account fallback → USD."""
from datetime import date, datetime
from odoo.tests import tagged

from .common import BillingTestCase


@tagged('whatsapp_billing', 'fx', 'post_install', '-at_install')
class TestFxResolution(BillingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ZAR = cls.env['res.currency'].search([('name', '=', 'ZAR')], limit=1)
        assert cls.ZAR, 'ZAR currency missing from base data'
        cls.account.billing_currency_id = cls.ZAR

    def _resolve(self, at):
        return self.env['whatsapp.billing.event']._resolve_fx(self.account, at)

    def test_account_currency_default_is_company_currency(self):
        acc = self.env['comm.whatsapp.account'].create({'name': 'Fresh WABA'})
        self.assertEqual(acc.billing_currency_id, self.env.company.currency_id)

    def test_meta_monthly_override_wins(self):
        self.env['whatsapp.fx.rate'].create({
            'date': date(2026, 6, 1),
            'currency_id': self.ZAR.id,
            'rate': 18.75,
        })
        fx, cur = self._resolve(datetime(2026, 6, 15, 12, 0))
        self.assertEqual(cur, self.ZAR)
        self.assertAlmostEqual(fx, 18.75, places=4)

    def test_falls_back_to_odoo_currency_rate(self):
        # No Meta override. Seed a res.currency.rate for USD in a ZAR company.
        # Odoo convention: rate = 1 (company currency) / (that currency), so for
        # a ZAR company with USD rate=0.05263, "1 ZAR = $0.05263" i.e. 1 USD = ~19 ZAR.
        self.env['res.currency.rate'].create({
            'name': date(2026, 5, 1),
            'currency_id': self.env.ref('base.USD').id,
            'rate': 1.0 / 19.0,
            'company_id': self.env.company.id,
        })
        fx, cur = self._resolve(datetime(2026, 5, 20))
        self.assertEqual(cur, self.ZAR)
        self.assertAlmostEqual(fx, 19.0, places=2)

    def test_account_fallback_used_when_no_other_source(self):
        self.env['whatsapp.fx.rate'].search([]).unlink()
        self.env['res.currency.rate'].search([
            ('currency_id', '=', self.env.ref('base.USD').id)
        ]).unlink()
        self.account.default_fx_rate = 17.5
        fx, cur = self._resolve(datetime(2026, 4, 1))
        self.assertEqual(cur, self.ZAR)
        self.assertAlmostEqual(fx, 17.5, places=4)

    def test_billing_event_populates_zar_price(self):
        self.env['whatsapp.fx.rate'].create({
            'date': date(2026, 6, 1),
            'currency_id': self.ZAR.id,
            'rate': 18.0,
        })
        msg = self._make_message(pricing_category='marketing',
                                 at=datetime(2026, 6, 15, 10, 0))
        ev = msg.billing_event_ids
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev.currency_id, self.ZAR)
        self.assertAlmostEqual(ev.price_usd, 0.0379, places=4)
        self.assertAlmostEqual(ev.price_local, 0.0379 * 18.0, places=4)

    def test_meta_fx_priority_over_odoo_rate(self):
        """Both sources present → Meta wins."""
        self.env['whatsapp.fx.rate'].create({
            'date': date(2026, 6, 1),
            'currency_id': self.ZAR.id,
            'rate': 18.0,
        })
        self.env['res.currency.rate'].create({
            'name': date(2026, 6, 1),
            'currency_id': self.env.ref('base.USD').id,
            'rate': 1.0 / 20.0,   # 1 USD = 20 ZAR
            'company_id': self.env.company.id,
        })
        fx, _ = self._resolve(datetime(2026, 6, 15))
        self.assertAlmostEqual(fx, 18.0, places=2)
