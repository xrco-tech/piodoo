# -*- coding: utf-8 -*-
"""A USSD code connected to a flow runs that flow, through either gateway;
a code that is not connected is answered by what answered it before."""
from urllib.parse import parse_qs

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged('post_install', '-at_install')
class TestUssdFlow(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['comm.bot.step']
        Option = cls.env['comm.bot.step.option']
        cls.ussd = cls.env.ref('comm_chatbot.channel_ussd')
        cls.wa = cls.env.ref('comm_chatbot.channel_whatsapp')
        # A draft flow: a welcome, a menu, and one screen behind each choice.
        cls.bot = cls.env['comm.bot'].create({
            'name': 'Telco', 'channel_ids': [(6, 0, cls.ussd.ids)]})
        cls.bye = Step.create({'bot_id': cls.bot.id, 'name': 'bye', 'kind': 'end',
                               'end_outcome': 'done'})
        cls.balance = Step.create({
            'bot_id': cls.bot.id, 'name': 'balance', 'kind': 'message',
            'body': 'Your balance is R5.', 'next_step_id': cls.bye.id})
        cls.ask = Step.create({
            'bot_id': cls.bot.id, 'name': 'ask', 'kind': 'input', 'input_type': 'text',
            'body': 'Which town?', 'input_save_to': 'town'})
        cls.town = Step.create({
            'bot_id': cls.bot.id, 'name': 'town', 'kind': 'message',
            'body': 'Thanks, {{state.town}}.', 'next_step_id': cls.bye.id})
        cls.ask.next_step_id = cls.town
        cls.menu = Step.create({
            'bot_id': cls.bot.id, 'name': 'menu', 'kind': 'menu', 'body': 'Please select:'})
        Option.create({'step_id': cls.menu.id, 'sequence': 10, 'label': 'Balance',
                       'value': '1', 'next_step_id': cls.balance.id})
        Option.create({'step_id': cls.menu.id, 'sequence': 20, 'label': 'My town',
                       'value': '2', 'next_step_id': cls.ask.id})
        cls.welcome = Step.create({
            'bot_id': cls.bot.id, 'name': 'welcome', 'kind': 'message',
            'body': 'Welcome to Telco.', 'next_step_id': cls.menu.id})
        cls.bot.entry_step_id = cls.welcome

        Account = cls.env['comm.ussd.account']
        cls.at = Account.create({'name': 'AT test', 'provider': 'africastalking',
                                 'service_code': '*555#'})
        cls.cm = Account.create({'name': 'CM test', 'provider': 'connect_mobile',
                                 'service_code': '*120*555#'})
        cls.Session = cls.env['comm.bot.ussd.session']

    # ── The two gateways ─────────────────────────────────────────────────

    def _at(self, session, text, code='*555#', phone='+27600000002'):
        return self.url_open('/ussd/inbound', timeout=30, data={
            'sessionId': session, 'serviceCode': code,
            'phoneNumber': phone, 'text': text}).text

    def _cm(self, session, kind, typed, phone='27600000003'):
        res = self.url_open('/ussd/connectmobile', timeout=30, data={
            'msisdn': phone, 'sessionid': session, 'request': typed,
            'type': str(kind), 'dialstring': '*120*555#', 'mno': 'mtn'})
        answer = parse_qs(res.text, keep_blank_values=True)
        return answer['text'][0], answer['session'][0]

    MENU = 'Welcome to Telco.\nPlease select:\n\n1. Balance\n2. My town'

    def test_africas_talking_code_runs_the_flow(self):
        self.at._connect_flow(self.bot)
        self.assertEqual(self._at('s1', ''), 'CON ' + self.MENU)
        self.assertEqual(self._at('s1', '1'), 'END Your balance is R5.')
        session = self.Session.search([('session_id', '=', 's1')])
        self.assertEqual((session.outcome, session.bot_id, session.account_id),
                         ('completed', self.bot, self.at))
        self.assertEqual(session.conversation_id.lifecycle_state, 'closed')
        event = session._billing_events()
        self.assertEqual((len(event), event.channel, event.category, event.service_code),
                         (1, 'ussd', 'ussd_session', '*555#'))

    def test_a_question_keeps_the_session_open(self):
        self.at._connect_flow(self.bot)
        self._at('s2', '')
        self.assertEqual(self._at('s2', '2'), 'CON Which town?')
        self.assertEqual(self._at('s2', '2*Soweto'), 'END Thanks, Soweto.')

    def test_a_wrong_answer_shows_the_menu_again(self):
        self.at._connect_flow(self.bot)
        self._at('s3', '')
        self.assertEqual(self._at('s3', '9'), 'CON Please select:\n\n1. Balance\n2. My town')
        self.assertEqual(self._at('s3', '9*1'), 'END Your balance is R5.')

    def test_connect_mobile_code_runs_the_flow(self):
        self.cm._connect_flow(self.bot)
        self.assertEqual(self._cm('77', 1, '*120*555#'), (self.MENU, '1'))
        self.assertEqual(self._cm('77', 2, '2'), ('Which town?', '1'))
        self.assertEqual(self._cm('77', 2, 'Durban'), ('Thanks, Durban.', '0'))
        session = self.Session.search([('phone_number', '=', '+27600000003')])
        self.assertEqual((len(session), session.outcome), (1, 'completed'))

    def test_connect_mobile_hang_up_closes_and_charges(self):
        self.cm._connect_flow(self.bot)
        self._cm('78', 1, '*120*555#')
        self._cm('78', 3, '')
        session = self.Session.search([('phone_number', '=', '+27600000003')])
        self.assertEqual(session.outcome, 'hangup')
        self.assertEqual(session.conversation_id.lifecycle_state, 'closed')
        self.assertEqual(len(session._billing_events()), 1)

    # ── What a dial must not do ──────────────────────────────────────────

    def test_each_dial_is_its_own_conversation(self):
        """A dial never picks up a conversation left open on another channel."""
        self.at._connect_flow(self.bot)
        partner = self.env['res.partner'].create({'name': 'Caller', 'mobile': '+27600000002'})
        other = self.env['comm.bot'].create({'name': 'WhatsApp bot'})
        left_open = self.env['comm.conversation'].create({
            'partner_id': partner.id, 'bot_id': other.id,
            'primary_channel_id': self.wa.id, 'lifecycle_state': 'waiting'})
        self.assertEqual(self._at('s4', ''), 'CON ' + self.MENU)
        self._at('s5', '')
        sessions = self.Session.search([('session_id', 'in', ('s4', 's5'))])
        self.assertEqual(len(sessions.conversation_id), 2)
        self.assertNotIn(left_open, sessions.conversation_id)
        self.assertEqual(sessions.conversation_id.partner_id, partner)
        self.assertEqual((left_open.bot_id, left_open.lifecycle_state), (other, 'waiting'))

    def test_a_code_that_is_not_connected_is_left_alone(self):
        """The same request, before and after another code is connected."""
        before = self._at('s6', '', code='*999#')
        self.at._connect_flow(self.bot)
        self.assertEqual(self._at('s7', '', code='*999#'), before)
        self.assertFalse(self.Session.search([('session_id', 'in', ('s6', 's7'))]))

    def test_disconnecting_stops_new_sessions_only(self):
        self.at._connect_flow(self.bot)
        self._at('s8', '')
        self.at._disconnect_flow()
        self.assertEqual(self._at('s8', '1'), 'END Your balance is R5.',
                         "a session already open is finished by the flow")
        self._at('s9', '')
        self.assertFalse(self.Session.search([('session_id', '=', 's9')]))

    # ── Connecting ───────────────────────────────────────────────────────

    def test_flow_must_run_on_ussd(self):
        other = self.env['comm.bot'].create({'name': 'No USSD'})
        with self.assertRaises(UserError):
            self.at._connect_flow(other)

    def test_another_engine_is_set_aside_and_put_back(self):
        """An account that runs its own coded menu (Chat2Work) goes back to
        it when the flow is disconnected."""
        if 'flow_engine' not in self.at._fields:
            self.skipTest('no other USSD engine is installed')
        self.at.flow_engine = 'chat2work'
        self.assertIn('Chat2Work', self.at._runs_now())
        self.at._connect_flow(self.bot)
        self.assertEqual((self.at.flow_engine, self.at.flow_previous_engine),
                         ('chatbot', 'chat2work'))
        self.assertEqual(self._at('s10', ''), 'CON ' + self.MENU)
        self.at._disconnect_flow()
        self.assertEqual((self.at.flow_engine, self.at.flow_previous_engine),
                         ('chat2work', False))
        reply = self._at('s11', '')
        self.assertFalse(self.Session.search([('session_id', '=', 's11')]),
                         "back with the coded menu, not the flow")
        self.assertIn(reply[:3], ('CON', 'END'))

    def test_adapter_reports_and_connects(self):
        from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter
        adapter = get_adapter('ussd')()
        self.assertFalse(adapter.connections(self.env, self.bot)[0]['ok'])
        option = next(o for o in adapter.connect_options(self.env, self.bot)
                      if o['id'] == self.at.id)
        self.assertFalse(option['connected'])
        adapter.connect(self.env, self.bot, self.at.id, True)
        line = adapter.connections(self.env, self.bot)[0]
        self.assertTrue(line['ok'])
        self.assertIn('*555#', line['text'])
        adapter.connect(self.env, self.bot, self.at.id, False)
        self.assertFalse(self.at.flow_bot_id)
