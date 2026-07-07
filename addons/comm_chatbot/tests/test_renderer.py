# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import ChatbotTestCase


@tagged('comm_chatbot', 'renderer', 'post_install', '-at_install')
class TestRenderer(ChatbotTestCase):

    def _fresh_conversation(self, channel):
        return self.env['comm.conversation'].create({
            'partner_id': self.partner.id,
            'bot_id': self.bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': self.step_greeting.id,
        })

    def test_variable_substitution(self):
        c = self._fresh_conversation(self.wa)
        r = self.env['comm.chatbot.renderer'].render(self.step_greeting, c)
        self.assertIn('Test', r['body'])

    def test_menu_options_on_wa_stay_as_options(self):
        c = self._fresh_conversation(self.wa)
        r = self.env['comm.chatbot.renderer'].render(self.step_menu, c)
        self.assertEqual(len(r['options']), 3)
        # WA supports lists; body shouldn't have embedded numbered menu
        self.assertNotIn('1. Balance', r['body'])

    def test_menu_options_degraded_to_numbered_text_on_sms(self):
        c = self._fresh_conversation(self.sms)
        r = self.env['comm.chatbot.renderer'].render(self.step_menu, c)
        self.assertIn('1. Balance', r['body'])
        self.assertIn('2. Payments', r['body'])

    def test_menu_options_degraded_to_con_menu_on_ussd(self):
        c = self._fresh_conversation(self.ussd)
        r = self.env['comm.chatbot.renderer'].render(self.step_menu, c)
        self.assertIn('1. Balance', r['body'])

    def test_hard_truncation(self):
        long_step = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'long',
            'kind': 'message', 'body': 'x' * 300,
            'truncation_strategy': 'hard',
        })
        c = self._fresh_conversation(self.ussd)  # max 182 chars
        r = self.env['comm.chatbot.renderer'].render(long_step, c)
        self.assertLessEqual(len(r['body']), 182)

    def test_channel_override(self):
        self.env['comm.bot.step.channel.override'].create({
            'step_id': self.step_greeting.id, 'channel_id': self.sms.id,
            'body_override': 'Hi {{contact.first_name}} - SMS version',
        })
        c_wa = self._fresh_conversation(self.wa)
        c_sms = self._fresh_conversation(self.sms)
        r_wa = self.env['comm.chatbot.renderer'].render(self.step_greeting, c_wa)
        r_sms = self.env['comm.chatbot.renderer'].render(self.step_greeting, c_sms)
        self.assertNotIn('SMS version', r_wa['body'])
        self.assertIn('SMS version', r_sms['body'])

    def test_missing_variable_lenient(self):
        step = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'missing',
            'kind': 'message', 'body': 'Balance: {{state.balance}}',
        })
        c = self._fresh_conversation(self.wa)
        r = self.env['comm.chatbot.renderer'].render(step, c)
        self.assertEqual(r['body'], 'Balance: ')

    def test_filters_currency(self):
        step = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'money',
            'kind': 'message', 'body': 'You owe {{state.due|currency:R}}',
        })
        c = self._fresh_conversation(self.wa)
        c.state = {'due': 1234.5}
        r = self.env['comm.chatbot.renderer'].render(step, c)
        self.assertIn('R 1,234.50', r['body'])
