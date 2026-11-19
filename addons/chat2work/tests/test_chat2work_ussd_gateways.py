# -*- coding: utf-8 -*-
"""The same Chat2Work flow reached through both gateways' own addresses."""

import json
from urllib.parse import parse_qs

from odoo.tests import HttpCase, tagged

AT_CODE = '*384*7001#'
CM_CODE = '*120*8800*7002#'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workUssdGateways(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.ussd.account']
        Account.create({'name': 'C2W AT', 'service_code': AT_CODE, 'provider': 'africastalking',
                        'flow_engine': 'chat2work'})
        Account.create({'name': 'C2W CM', 'service_code': CM_CODE, 'provider': 'connect_mobile',
                        'flow_engine': 'chat2work'})

    def cm(self, **data):
        """One Connect Mobile request, form-posted; the answer as a dict."""
        res = self.url_open('/ussd/connectmobile', data=data, timeout=30)
        self.assertEqual(res.status_code, 200)
        answer = parse_qs(res.text, keep_blank_values=True)
        return answer['text'][0], answer['session'][0]

    def test_connect_mobile_session(self):
        Session = self.env['chat2work.ussd.session']
        Held = self.env['comm.ussd.gateway.session']
        text, session = self.cm(msisdn='27820007001', sessionid='555', network='2', request=CM_CODE,
                                type='1', dialstring=CM_CODE, mno='mtn')
        self.assertEqual(session, '1')
        self.assertIn('Chat2Work', text)
        live = Session.search([('msisdn', '=', '+27820007001')])
        self.assertEqual(len(live), 1)
        self.assertEqual(live.service_code, CM_CODE)
        self.assertEqual(Held.search([('key', '=', '555/27820007001')]).network, 'mtn')
        # The caller answers 0 (exit): only the latest entry is sent, with no code.
        text, session = self.cm(msisdn='27820007001', sessionid='555', request='0', type='2')
        self.assertEqual(session, '0')
        self.assertFalse(Session.search([('msisdn', '=', '+27820007001')]))
        self.assertFalse(Held.search([('key', '=', '555/27820007001')]))

    def test_connect_mobile_hang_up_and_reused_number(self):
        Session = self.env['chat2work.ussd.session']
        start = dict(msisdn='27820007003', sessionid='777', request=CM_CODE, type='1', dialstring=CM_CODE)
        self.assertEqual(self.cm(**start)[1], '1')
        # Type 3: the caller hung up. The session is closed and nothing is shown.
        self.assertEqual(self.cm(msisdn='27820007003', sessionid='777', request='', type='3')[1], '0')
        self.assertFalse(Session.search([('msisdn', '=', '+27820007003')]))
        # The network uses the same session number again: a fresh session, not the old one.
        self.assertEqual(self.cm(**start)[1], '1')
        self.assertEqual(Session.search_count([('msisdn', '=', '+27820007003')]), 1)
        # An answer for a session we never held ends politely.
        text, session = self.cm(msisdn='27820007004', sessionid='888', request='1', type='2')
        self.assertEqual(session, '0')

    def test_connect_mobile_json_and_wrong_gateway(self):
        res = self.url_open('/ussd/connectmobile', data=json.dumps({
            'msisdn': '27820007005', 'sessionid': '999', 'network': 1, 'request': CM_CODE, 'type': 1,
            'menu': 'none', 'option': '*', 'dialstring': CM_CODE, 'mccmnc': '65501', 'mno': 'vodacom',
            'reference': None}), headers={'Content-Type': 'application/json'}, timeout=30)
        answer = res.json()
        self.assertEqual(answer['session'], 1)
        self.assertIn('Chat2Work', answer['text'])
        # An Africa's Talking code is not answered on Connect Mobile's address.
        text, session = self.cm(msisdn='27820007006', sessionid='1000', request=AT_CODE, type='1',
                                dialstring=AT_CODE)
        self.assertEqual(session, '0')
        self.assertFalse(self.env['chat2work.ussd.session'].search([('msisdn', '=', '+27820007006')]))

    def test_africas_talking_still_answers(self):
        Session = self.env['chat2work.ussd.session']
        post = lambda **d: self.url_open('/ussd/inbound', data=d, timeout=30).text
        first = post(sessionId='ATUid_gw_1', serviceCode=AT_CODE, phoneNumber='+27820007007', text='')
        self.assertTrue(first.startswith('CON '), first)
        self.assertEqual(Session.search_count([('session_id', '=', 'ATUid_gw_1')]), 1)
        last = post(sessionId='ATUid_gw_1', serviceCode=AT_CODE, phoneNumber='+27820007007', text='0')
        self.assertTrue(last.startswith('END '), last)
        # A session left open is closed by the end-of-session notice.
        post(sessionId='ATUid_gw_2', serviceCode=AT_CODE, phoneNumber='+27820007008', text='')
        self.url_open('/ussd/notifications', data={'sessionId': 'ATUid_gw_2', 'status': 'Incomplete'}, timeout=30)
        self.assertFalse(Session.search([('session_id', '=', 'ATUid_gw_2')]))
