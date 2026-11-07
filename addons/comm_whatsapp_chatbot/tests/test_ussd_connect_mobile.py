# -*- coding: utf-8 -*-
"""Connect Mobile USSD endpoint: formats, session lifecycle, token check."""

import json
from urllib.parse import parse_qs

from lxml import etree

from odoo.tests import common, tagged


@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdConnectMobile(common.HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['comm.ussd.account'].create({
            'name': 'CM Code', 'provider': 'connect_mobile', 'service_code': '*120*55555#',
        })
        cls.other_account = cls.env['comm.ussd.account'].create({
            'name': 'AT Code', 'provider': 'africastalking', 'service_code': '*384*1#',
        })
        Step = cls.env['whatsapp.chatbot.step']
        cls.bot = cls.env['whatsapp.chatbot'].create({
            'name': 'CM USSD Bot', 'channel': 'ussd', 'status': 'published',
            'ussd_account_id': cls.account.id,
        })
        welcome = Step.create({
            'name': 'Welcome', 'chatbot_id': cls.bot.id, 'step_type': 'message',
            'body_plain': 'Welcome to CM', 'sequence': 1,
        })
        question = Step.create({
            'name': 'Question', 'chatbot_id': cls.bot.id, 'step_type': 'question_text',
            'body_plain': 'Pick an option', 'parent_id': welcome.id, 'sequence': 10,
        })
        option_a = Step.create({
            'name': 'Option A', 'chatbot_id': cls.bot.id, 'step_type': 'message',
            'body_plain': 'You chose A', 'parent_id': question.id, 'sequence': 10,
        })
        Step.create({
            'name': 'End', 'chatbot_id': cls.bot.id, 'step_type': 'end_flow',
            'parent_id': option_a.id,
        })
        answer = cls.env['whatsapp.chatbot.answer'].create({
            'value': '1', 'step_id': option_a.id, 'operator': 'is_equal_to',
        })
        option_a.write({'trigger_answer_ids': [(4, answer.id)]})

    def _url(self, account=None):
        return f'/ussd/connectmobile?token={(account or self.account).webhook_token}'

    def _form(self, sessionid, type_, request_text, **extra):
        data = {'msisdn': '27820000123', 'sessionid': sessionid, 'type': str(type_),
                'request': request_text, 'mno': 'mtn', 'network': '2'}
        data.update(extra)
        response = self.url_open(self._url(), data=data)
        self.assertEqual(response.status_code, 200)
        parsed = parse_qs(response.text, keep_blank_values=True)
        return parsed['text'][0], parsed['session'][0]

    def _session(self, sessionid):
        return self.env['whatsapp.chatbot.ussd.session'].search([('session_id', '=', f'cm:{sessionid}')])

    def test_form_flow_first_screen_then_end(self):
        text, session = self._form('s1', 1, '*120*55555#')
        self.assertEqual(session, '1')
        self.assertIn('Welcome to CM', text)
        self.assertIn('Pick an option', text)
        record = self._session('s1')
        self.assertEqual(record.ussd_account_id, self.account)
        self.assertEqual(record.carrier, 'mtn')
        self.assertEqual(record.service_code, '*120*55555#')

        text, session = self._form('s1', 2, '1')
        self.assertEqual(session, '0')
        self.assertIn('You chose A', text)
        self.assertEqual(record.outcome, 'completed')
        self.assertEqual(record.breadcrumb, '1')

    def test_json_format(self):
        response = self.url_open(
            self._url(),
            data=json.dumps({'msisdn': '27820000123', 'sessionid': 'j1', 'type': 1,
                             'request': '*120*55555#', 'mno': 'vodacom', 'reference': None}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/json', response.headers['Content-Type'])
        body = response.json()
        self.assertEqual(body['session'], 1)
        self.assertIn('Welcome to CM', body['text'])

    def test_xml_format(self):
        xml = ('<ussd><msisdn>27820000123</msisdn><sessionid>x1</sessionid><network>1</network>'
               '<request type="1">*120*55555#</request><menu>none</menu><option>*</option></ussd>')
        response = self.url_open(self._url(), data=xml, headers={'Content-Type': 'application/xml'})
        self.assertEqual(response.status_code, 200)
        root = etree.fromstring(response.content)
        self.assertEqual(root.tag, 'ussd')
        self.assertEqual(root.findtext('session'), '1')
        self.assertIn('Welcome to CM', root.findtext('text'))

    def test_get_request(self):
        response = self.url_open(
            self._url() + '&msisdn=27820000123&sessionid=g1&type=1&request=%2A120%2A55555%23')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(parse_qs(response.text)['session'], ['1'])

    def test_hangup_and_timeout_close_session(self):
        self._form('h1', 1, '*120*55555#')
        text, session = self._form('h1', 3, '')
        self.assertEqual((text, session), ('', '0'))
        self.assertEqual(self._session('h1').outcome, 'hangup')

        self._form('t1', 1, '*120*55555#')
        self._form('t1', 4, '')
        self.assertEqual(self._session('t1').outcome, 'timeout')

    def test_reused_session_id_starts_fresh(self):
        self._form('r1', 1, '*120*55555#')
        self._form('r1', 2, '1')
        old = self._session('r1')
        self.assertEqual(old.outcome, 'completed')

        text, session = self._form('r1', 1, '*120*55555#')
        self.assertEqual(session, '1')
        self.assertIn('Welcome to CM', text)
        new = self._session('r1')
        self.assertNotEqual(new, old)
        self.assertEqual(new.outcome, 'open')
        self.assertEqual(old.session_id, f'cm:r1:{old.id}')

    def test_reused_open_session_id_retires_old_session(self):
        self._form('r2', 1, '*120*55555#')
        old = self._session('r2')
        self._form('r2', 1, '*120*55555#')
        self.assertEqual(old.outcome, 'timeout')
        self.assertEqual(self._session('r2').outcome, 'open')

    def test_reply_without_open_session_ends(self):
        text, session = self._form('none1', 2, '1')
        self.assertEqual(session, '0')
        self.assertIn('expired', text)
        self.assertFalse(self._session('none1'))

    def test_bad_token_rejected(self):
        data = {'msisdn': '27820000123', 'sessionid': 'b1', 'type': '1', 'request': '*120*55555#'}
        self.assertEqual(self.url_open('/ussd/connectmobile', data=data).status_code, 403)
        self.assertEqual(self.url_open('/ussd/connectmobile?token=wrong', data=data).status_code, 403)
        # Another provider's token does not open the Connect Mobile endpoint
        self.assertEqual(self.url_open(self._url(self.other_account), data=data).status_code, 403)
        self.assertFalse(self._session('b1'))

    def test_account_callback_url(self):
        self.assertTrue(self.account.callback_url.endswith(
            f'/ussd/connectmobile?token={self.account.webhook_token}'))
        self.assertFalse(self.other_account.callback_url)
        token = self.account.webhook_token
        self.account.action_regenerate_webhook_token()
        self.assertNotEqual(self.account.webhook_token, token)


@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdInboundRoute(common.HttpCase):
    """The Africa's Talking-shaped /ussd/inbound route still starts and
    continues sessions after sharing its session-start code."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env['comm.ussd.account'].create({
            'name': 'AT Route', 'provider': 'africastalking', 'service_code': '*384*77#',
        })
        bot = cls.env['whatsapp.chatbot'].create({
            'name': 'AT Route Bot', 'channel': 'ussd', 'status': 'published',
            'ussd_account_id': cls.account.id,
        })
        Step = cls.env['whatsapp.chatbot.step']
        root = Step.create({
            'name': 'Ask', 'chatbot_id': bot.id, 'step_type': 'question_text',
            'body_plain': 'Your name?', 'sequence': 1,
        })
        Step.create({
            'name': 'Bye', 'chatbot_id': bot.id, 'step_type': 'message',
            'body_plain': 'Thanks', 'parent_id': root.id, 'sequence': 10,
        })

    def test_first_and_second_turn(self):
        data = {'sessionId': 'ATUid_route1', 'serviceCode': '*384*77#',
                'phoneNumber': '+27820000456', 'text': ''}
        response = self.url_open('/ussd/inbound', data=data)
        self.assertEqual(response.text, 'CON Your name?')
        session = self.env['whatsapp.chatbot.ussd.session'].search([('session_id', '=', 'ATUid_route1')])
        self.assertTrue(session.contact_id)

        response = self.url_open('/ussd/inbound', data=dict(data, text='Sam'))
        self.assertTrue(response.text.startswith('END '), response.text)
        self.assertIn('Thanks', response.text)
