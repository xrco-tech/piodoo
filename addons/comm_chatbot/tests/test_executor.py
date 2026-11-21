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

    def _route(self, value):
        """A condition on which value state.route has: sfm, lead, or other."""
        Step = self.env['comm.bot.step']
        Option = self.env['comm.bot.step.option']
        tag = str(value).strip() or 'none'
        check = Step.create({
            'bot_id': self.bot.id, 'name': 'route_' + tag, 'kind': 'condition',
            'condition_mode': 'equals',
            'condition_expression': '{{state.route}}',
        })
        for label, default in (('sfm', False), ('lead', False), ('other', True)):
            end = Step.create({'bot_id': self.bot.id,
                               'name': 'end_%s_%s' % (label, tag),
                               'kind': 'end', 'end_outcome': label})
            Option.create({'step_id': check.id, 'label': label, 'value': label,
                           'is_default': default, 'next_step_id': end.id})
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id, 'current_step_id': check.id,
            'state': {'route': value} if value is not None else {},
        })
        self.env['comm.chatbot.executor'].advance(c)
        return c.outcome

    def test_condition_by_value(self):
        self.assertEqual(self._route('sfm'), 'sfm')
        self.assertEqual(self._route(' LEAD '), 'lead', "case and spaces ignored")
        self.assertEqual(self._route('unknown'), 'other',
                         "a value no branch names takes the default branch")
        self.assertEqual(self._route(None), 'other')

    def _render(self, step, channel):
        c = self.env['comm.conversation'].new({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': channel.id, 'state': {}})
        return self.env['comm.chatbot.renderer'].render(step, c)

    def test_header_and_footer_per_channel(self):
        self.wa.supports_header_footer = True
        self.step_menu.write({'header': 'Hi {{contact.first_name}}', 'footer': 'Reply STOP to leave'})
        on_wa = self._render(self.step_menu, self.wa)
        self.assertEqual((on_wa['header'], on_wa['body'], on_wa['footer']),
                         ('Hi Test', 'Choose:', 'Reply STOP to leave'))
        on_ussd = self._render(self.step_menu, self.ussd)
        self.assertEqual((on_ussd['header'], on_ussd['footer']), ('', ''))
        self.assertEqual(
            on_ussd['body'],
            'Hi Test\nChoose:\n\n1. Balance\n2. Payments\n3. Help\nReply STOP to leave')
        # A step with neither is unchanged.
        plain = self._render(self.step_greeting, self.ussd)
        self.assertEqual(plain['body'], 'Hello Test')

    def test_long_button_label_matches_its_cut_reply(self):
        option = self.step_menu.option_ids.sorted('sequence')[1]
        option.write({'label': 'Payments and statements for this month', 'value': 'pay'})
        c = self.env['comm.conversation'].create({
            'partner_id': self.partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id, 'current_step_id': self.step_menu.id})
        picked = self.env['comm.chatbot.executor']._match_option(
            self.step_menu, 'Payments and stateme', c)
        self.assertEqual(picked['value'], 'pay')
