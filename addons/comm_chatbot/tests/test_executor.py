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

    def test_menu_after_message_is_sent(self):
        """A message followed by a menu sends both, then waits."""
        c = self.env['comm.chatbot.executor'].start(
            self.bot, self.partner, 'whatsapp')
        sent = c.interaction_ids.filtered(lambda i: i.direction == 'outbound')
        self.assertEqual(sent.mapped('step_id'),
                         self.step_greeting | self.step_menu)
        self.assertEqual(c.lifecycle_state, 'waiting')

    def test_set_variable_keeps_a_value(self):
        Step = self.env['comm.bot.step']
        end = Step.create({'bot_id': self.bot.id, 'name': 'stop', 'kind': 'end'})
        keep = Step.create({
            'bot_id': self.bot.id, 'name': 'keep', 'kind': 'set_variable',
            'set_variable_name': 'greeting',
            'set_variable_value': 'Hi {{contact.first_name}}',
            'next_step_id': end.id,
        })
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id, 'current_step_id': keep.id,
        })
        self.env['comm.chatbot.executor'].advance(c)
        self.assertEqual(c.state['greeting'], 'Hi Test')
        self.assertEqual(c.lifecycle_state, 'closed')

    def _other_bot(self):
        """A second bot: asks one question, then ends."""
        Step = self.env['comm.bot.step']
        other = self.env['comm.bot'].create({
            'name': 'Other bot', 'engine_mode': 'shadow',
            'channel_ids': [(6, 0, [self.wa.id])],
        })
        stop = Step.create({'bot_id': other.id, 'name': 'stop', 'kind': 'end'})
        ask = Step.create({
            'bot_id': other.id, 'name': 'ask', 'kind': 'input',
            'body': 'Which town?', 'input_type': 'text',
            'input_save_to': 'town', 'next_step_id': stop.id,
        })
        other.entry_step_id = ask
        return other

    def test_jump_and_come_back(self):
        Step = self.env['comm.bot.step']
        Exec = self.env['comm.chatbot.executor']
        other = self._other_bot()
        after = Step.create({
            'bot_id': self.bot.id, 'name': 'after', 'kind': 'message',
            'body': 'Thanks, {{state.place}}.',
        })
        jump = Step.create({
            'bot_id': self.bot.id, 'name': 'go', 'kind': 'jump',
            'jump_target_bot_id': other.id, 'jump_return': True,
            'jump_mapping': [{'from': 'place', 'to': 'town', 'direction': 'out'}],
            'next_step_id': after.id,
        })
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id, 'current_step_id': jump.id,
        })
        Exec.advance(c)
        self.assertEqual(c.bot_id, other, "now inside the other bot")
        self.assertEqual(c.current_step_id, other.entry_step_id)
        self.assertEqual(c.lifecycle_state, 'waiting')
        Exec._handle_input(c, None, 'Soweto')
        self.assertEqual(c.bot_id, self.bot, "back in the first bot")
        self.assertEqual(c.state['place'], 'Soweto')
        self.assertFalse(c.state['__stack'])
        last = c.interaction_ids.filtered(
            lambda i: i.direction == 'outbound').sorted('id')[-1]
        self.assertEqual(last.rendered_body, 'Thanks, Soweto.')

    def test_jump_without_return_does_not_come_back(self):
        other = self._other_bot()
        jump = self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'go', 'kind': 'jump',
            'jump_target_bot_id': other.id,
            'next_step_id': self.step_end.id,
        })
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id, 'current_step_id': jump.id,
        })
        self.env['comm.chatbot.executor'].advance(c)
        self.assertEqual(c.bot_id, self.bot)
        self.assertFalse((c.state or {}).get('__stack'))
