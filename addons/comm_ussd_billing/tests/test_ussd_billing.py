# -*- coding: utf-8 -*-
"""USSD session → billing event: provider label, Connect Mobile 20 s blocks."""
from datetime import timedelta

from odoo import fields
from odoo.tests import common, tagged


@tagged('comm_billing', 'ussd', 'post_install', '-at_install')
class TestUssdBilling(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.ussd.account']
        cls.cm_account = Account.create({
            'name': 'CM', 'provider': 'connect_mobile', 'service_code': '*120*55556#'})
        cls.at_account = Account.create({
            'name': 'AT', 'provider': 'africastalking', 'service_code': '*384*2#'})
        cls.bot = cls.env['whatsapp.chatbot'].create({
            'name': 'Billing Bot', 'channel': 'ussd', 'status': 'published'})

    def _session(self, account, carrier=False, age_seconds=0, sid='b'):
        session = self.env['whatsapp.chatbot.ussd.session'].create({
            'session_id': sid, 'phone_number': '27820000123',
            'chatbot_id': self.bot.id, 'ussd_account_id': account.id, 'carrier': carrier,
        })
        self.env.cr.execute(
            "UPDATE whatsapp_chatbot_ussd_session SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(seconds=age_seconds), session.id))
        session.invalidate_recordset(['create_date'])
        return session

    def test_connect_mobile_bills_per_started_20_seconds(self):
        session = self._session(self.cm_account, carrier='mtn', age_seconds=45, sid='cm1')
        session.outcome = 'completed'
        event = session.billing_event_ids
        self.assertEqual(len(event), 1)
        self.assertEqual(event.provider, 'Connect Mobile')
        self.assertEqual(event.unit, 'ussd_20s')
        self.assertEqual(event.unit_qty, 3.0)
        self.assertEqual(event.rate_card_id, self.env.ref('comm_ussd_billing.rate_card_ussd_connect_mobile'))
        self.assertAlmostEqual(event.price_usd, 3 * 0.012222, places=6)

    def test_connect_mobile_other_networks_use_default_rate(self):
        session = self._session(self.cm_account, carrier='vodacom', age_seconds=5, sid='cm2')
        session.outcome = 'hangup'
        event = session.billing_event_ids
        self.assertEqual(event.unit_qty, 1.0)
        self.assertAlmostEqual(event.price_usd, 0.011111, places=6)

    def test_africastalking_session_keeps_per_session_card(self):
        session = self._session(self.at_account, age_seconds=50, sid='at1')
        session.outcome = 'completed'
        event = session.billing_event_ids
        self.assertEqual(event.provider, "Africa's Talking")
        self.assertEqual((event.unit, event.unit_qty), ('session', 1.0))
        self.assertEqual(event.rate_card_id, self.env.ref('comm_ussd_billing.rate_card_ussd_africas_talking'))
