# -*- coding: utf-8 -*-
"""An SMS that is a flow's keyword starts the flow, on the sender the flow is
connected to; the next SMS is the answer. Flows are test only: nothing is sent."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter


@tagged('comm_chatbot_sms', 'post_install', '-at_install')
class TestSmsKeywords(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['comm.bot.step']
        Account = cls.env['comm.sms.account']
        Account.search([]).write({'active': False})
        cls.main = Account.create({'name': 'Short code', 'sender_id': '32001', 'is_default': True})
        cls.other = Account.create({'name': 'Second code', 'sender_id': '32002'})
        cls.named = Account.create({'name': 'Brand name', 'sender_id': 'Chat2Work'})
        cls.sms = cls.env.ref('comm_chatbot.channel_sms')
        cls.bot = cls.env['comm.bot'].create({
            'name': 'Jobs by SMS', 'channel_ids': [(6, 0, cls.sms.ids)],
            'engine_mode': 'shadow', 'sms_account_id': cls.main.id})
        cls.bye = Step.create({'bot_id': cls.bot.id, 'name': 'bye', 'kind': 'end',
                               'end_outcome': 'done'})
        cls.thanks = Step.create({
            'bot_id': cls.bot.id, 'name': 'thanks', 'kind': 'message',
            'body': 'Thanks, {{state.town}}.', 'next_step_id': cls.bye.id})
        cls.ask = Step.create({
            'bot_id': cls.bot.id, 'name': 'ask', 'kind': 'input', 'input_type': 'text',
            'body': 'Which town?', 'input_save_to': 'town', 'next_step_id': cls.thanks.id})
        cls.bot.entry_step_id = cls.ask
        cls.env['comm.bot.trigger'].create({
            'bot_id': cls.bot.id, 'channel_id': cls.sms.id, 'kind': 'keyword',
            'value': 'Jobs', 'match_mode': 'exact'})
        cls.Sms = cls.env['sms.sms']
        cls.partner = cls.env['res.partner'].create({'name': 'Thandi', 'mobile': '+27 82 555 0303'})

    def _sms(self, body, to='32001'):
        return self.Sms._comm_record_inbound(self.partner, '27825550303', body, 'mo', to)

    def test_keyword_starts_the_flow_and_the_next_sms_answers(self):
        first = self._sms(' jobs ')
        conversation = first.conversation_id
        self.assertEqual(conversation.bot_id, self.bot)
        self.assertEqual(conversation.current_step_id, self.ask)
        self.assertEqual(conversation.lifecycle_state, 'waiting')
        self.assertEqual((first.direction, first.raw_body, first.channel_id),
                         ('inbound', ' jobs ', self.sms))
        second = self._sms('Soweto')
        self.assertEqual(second.conversation_id, conversation)
        self.assertEqual(conversation.state.get('town'), 'Soweto')
        self.assertEqual((conversation.lifecycle_state, conversation.outcome), ('closed', 'done'))
        # One contact, one record per SMS: nothing is kept twice.
        inbound = self.env['comm.interaction'].search([
            ('conversation_id.partner_id', '=', self.partner.id), ('direction', '=', 'inbound')])
        self.assertEqual(len(inbound), 2)

    def test_only_on_the_sender_the_flow_is_connected_to(self):
        kept = self._sms('jobs', to='32002')
        self.assertFalse(kept.conversation_id.bot_id)
        self.assertEqual(kept.raw_body, 'jobs')

    def test_sender_written_another_way_and_no_sender_at_all(self):
        self.assertEqual(self._sms('jobs', to='+32001').conversation_id.bot_id, self.bot)
        self.partner = self.env['res.partner'].create({'name': 'Sipho', 'mobile': '+27 82 555 0404'})
        started = self.Sms._comm_record_inbound(self.partner, '27825550404', 'JOBS', 'mo', None)
        self.assertEqual(started.conversation_id.bot_id, self.bot)

    def test_other_words_are_only_kept(self):
        kept = self._sms('What jobs do you have?')
        self.assertFalse(kept.conversation_id.bot_id)
        # The keyword then starts the flow in the conversation already open.
        started = self._sms('Jobs')
        self.assertEqual(started.conversation_id, kept.conversation_id)
        self.assertEqual(started.conversation_id.current_step_id, self.ask)

    def test_a_conversation_with_a_person_is_left_alone(self):
        kept = self._sms('hello')
        kept.conversation_id.lifecycle_state = 'handoff'
        again = self._sms('jobs')
        self.assertEqual(again.conversation_id, kept.conversation_id)
        self.assertFalse(again.conversation_id.bot_id)

    def test_a_draft_flow_does_not_start(self):
        self.bot.engine_mode = 'draft'
        self.assertFalse(self._sms('jobs').conversation_id.bot_id)

    def test_through_the_webhook_entry(self):
        if 'whatsapp.chatbot.message' not in self.env:
            self.skipTest('comm_whatsapp_chatbot not installed')
        self.env['whatsapp.chatbot.message'].process_incoming_sms_message(
            from_number='27825550303', message_text='JOBS', sms_message_id='mo-9',
            to_number='32001')
        conversation = self.env['comm.conversation'].search([('partner_id', '=', self.partner.id)])
        self.assertEqual((len(conversation), conversation.bot_id, conversation.current_step_id),
                         (1, self.bot, self.ask))

    def test_what_the_flow_screen_is_told(self):
        adapter = get_adapter('sms')
        self.assertTrue(adapter.keyword_start)
        texts = [line['text'] for line in adapter().connections(self.env, self.bot)]
        self.assertEqual(len(texts), 1)
        self.bot.sms_account_id = self.named
        texts = [line['text'] for line in adapter().connections(self.env, self.bot)]
        self.assertTrue(any('is a name, not a number' in text for text in texts))
        self.bot.trigger_ids.unlink()
        texts = [line['text'] for line in adapter().connections(self.env, self.bot)]
        self.assertTrue(any('No keyword starts this flow' in text for text in texts))
        self.assertFalse(any('is a name' in text for text in texts))
