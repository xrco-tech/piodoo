# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import ChatbotTestCase


@tagged('comm_chatbot', 'triggers', 'post_install', '-at_install')
class TestTriggers(ChatbotTestCase):

    def setUp(self):
        super().setUp()
        self.bot.engine_mode = 'live'
        self.trigger = self.env['comm.bot.trigger'].create({
            'bot_id': self.bot.id,
            'channel_id': self.wa.id,
            'kind': 'keyword',
            'value': 'start',
            'match_mode': 'exact',
        })

    def test_exact_match(self):
        found = self.env['comm.bot.trigger'].find_trigger('whatsapp', 'start')
        self.assertEqual(found, self.trigger)

    def test_no_match(self):
        found = self.env['comm.bot.trigger'].find_trigger('whatsapp', 'hello')
        self.assertFalse(found)

    def test_prefix_match(self):
        self.trigger.match_mode = 'prefix'
        self.trigger.value = 'help'
        found = self.env['comm.bot.trigger'].find_trigger('whatsapp', 'help me pls')
        self.assertEqual(found, self.trigger)

    def test_case_insensitive_by_default(self):
        found = self.env['comm.bot.trigger'].find_trigger('whatsapp', 'START')
        self.assertEqual(found, self.trigger)

    def test_disabled_bot_not_matched(self):
        self.bot.engine_mode = 'paused'
        found = self.env['comm.bot.trigger'].find_trigger('whatsapp', 'start')
        self.assertFalse(found)
