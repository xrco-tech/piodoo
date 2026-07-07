# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import ChatbotTestCase


@tagged('comm_chatbot', 'executor', 'post_install', '-at_install')
class TestExecutor(ChatbotTestCase):

    def test_start_creates_conversation_and_advances(self):
        self.bot.engine_mode = 'shadow'
        # There's no adapter for these channels in test env (no channel addons
        # loaded), so we rely on shadow-mode short-circuit.
        c = self.env['comm.chatbot.executor'].start(
            self.bot, self.partner, 'whatsapp')
        self.assertTrue(c)
        # After greeting → menu, engine is waiting
        self.assertEqual(c.current_step_id, self.step_menu)
        self.assertEqual(c.lifecycle_state, 'waiting')

    def test_menu_input_advances(self):
        c = self.env['comm.chatbot.executor'].start(
            self.bot, self.partner, 'whatsapp')
        # Simulate an inbound "1"
        source = self.env['comm.interaction']  # placeholder
        c.write({'current_step_id': self.step_menu.id, 'lifecycle_state': 'waiting'})
        self.env['comm.chatbot.executor']._handle_input(c, None, '1')
        self.assertEqual(c.current_step_id, self.step_end)
        self.assertEqual(c.lifecycle_state, 'closed')

    def test_condition_step_branches(self):
        step_cond = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'is_vip',
            'kind': 'condition',
            'condition_expression': '{{state.vip}}',
        })
        step_yes = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'yes_branch',
            'kind': 'end', 'end_outcome': 'vip',
        })
        step_no = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'no_branch',
            'kind': 'end', 'end_outcome': 'normal',
        })
        self.env['comm.bot.step.option'].create({
            'step_id': step_cond.id, 'label': 'yes', 'value': 'yes',
            'next_step_id': step_yes.id,
        })
        self.env['comm.bot.step.option'].create({
            'step_id': step_cond.id, 'label': 'no', 'value': 'no',
            'is_default': True, 'next_step_id': step_no.id,
        })
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id,
            'current_step_id': step_cond.id,
            'state': {'vip': True},
        })
        self.env['comm.chatbot.executor'].advance(c)
        self.assertEqual(c.outcome, 'vip')

    def test_shadow_mode_does_not_send(self):
        c = self.env['comm.chatbot.executor'].start(
            self.bot, self.partner, 'whatsapp')
        # No source_id should exist on any outbound interaction (shadow skipped)
        outbound = c.interaction_ids.filtered(lambda i: i.direction == 'outbound')
        self.assertTrue(outbound)
        for i in outbound:
            self.assertFalse(i.source_id)
