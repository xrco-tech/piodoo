# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBringOver(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Old = cls.env['whatsapp.chatbot']
        cls.OldStep = cls.env['whatsapp.chatbot.step']
        cls.Answer = cls.env['whatsapp.chatbot.answer']
        cls.Importer = cls.env['sediba.flows.importer']

    def _old(self, name, channel='whatsapp'):
        return self.Old.create({'name': name, 'channel': channel})

    def _step(self, bot, name, kind='message', parent=None, **vals):
        return self.OldStep.create(dict(
            vals, chatbot_id=bot.id, name=name, step_type=kind,
            parent_id=parent.id if parent else False))

    def _answer(self, child, value):
        answer = self.Answer.create({'step_id': child.id, 'value': value})
        child.trigger_answer_ids = [(4, answer.id)]
        return answer

    def _by_name(self, flow):
        return {s.name: s for s in flow.step_ids}

    def test_straight_line(self):
        """Message, question, keep the answer, end."""
        old = self._old('Signup')
        name_var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': old.id, 'name': 'player_name', 'data_type': 'text'})
        hello = self._step(old, 'Hello', body_plain='Welcome', footer='Reply STOP to leave')
        ask = self._step(old, 'Ask name', 'question_text', hello,
                         body_plain='Your name?')
        keep = self._step(old, 'Keep name', 'set_variable', ask,
                          variable_id=name_var.id, variable_data_source='answer',
                          source_step_id=ask.id)
        thanks = self._step(old, 'Thanks', parent=keep,
                            body_plain='Thanks {{variables.player_name}}')
        self._step(old, 'Done', 'end_flow', thanks)

        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        self.assertEqual(flow.engine_mode, 'draft')
        self.assertEqual(flow.legacy_chatbot_id, old)
        self.assertEqual(flow.channel_ids.code, 'whatsapp')
        self.assertEqual(flow.entry_step_id, s['Hello'])
        self.assertEqual(s['Hello'].kind, 'message')
        self.assertEqual(s['Hello'].body, 'Welcome')
        self.assertEqual(s['Hello'].footer, 'Reply STOP to leave')
        self.assertEqual(s['Hello'].next_step_id, s['Ask name'])
        self.assertEqual(s['Ask name'].kind, 'input')
        self.assertEqual(s['Ask name'].input_save_to, 'answer_ask_name')
        self.assertEqual(s['Keep name'].kind, 'set_variable')
        self.assertEqual(s['Keep name'].set_variable_name, 'player_name')
        self.assertEqual(s['Keep name'].set_variable_value, '{{state.answer_ask_name}}')
        self.assertEqual(s['Thanks'].body, 'Thanks {{state.player_name}}')
        self.assertEqual(s['Thanks'].next_step_id, s['Done'])
        self.assertEqual(s['Done'].kind, 'end')
        self.assertEqual(flow.variable_ids.name, 'player_name')
        self.assertIn('5 steps', flow.import_notes)
        self.assertEqual(len(old.step_ids), 5, "the older bot is untouched")

    def test_walks_like_the_older_bot(self):
        """The copy, run by the newer engine, says the same things."""
        old = self._old('Signup')
        hello = self._step(old, 'Hello', body_plain='Welcome')
        ask = self._step(old, 'Ask name', 'question_text', hello, body_plain='Your name?')
        var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': old.id, 'name': 'who', 'data_type': 'text'})
        keep = self._step(old, 'Keep', 'set_variable', ask, variable_id=var.id,
                          variable_data_source='answer', source_step_id=ask.id)
        self._step(old, 'Thanks', parent=keep, body_plain='Thanks {{variables.who}}')
        flow = self.Importer.import_bot(old)
        flow.engine_mode = 'shadow'
        partner = self.env['res.partner'].create({'name': 'Test Contact'})
        Exec = self.env['comm.chatbot.executor']
        c = Exec.start(flow, partner, 'whatsapp')
        said = lambda: c.interaction_ids.filtered(
            lambda i: i.direction == 'outbound').sorted('id').mapped('rendered_body')
        self.assertEqual(said(), ['Welcome', 'Your name?'])
        Exec._handle_input(c, None, 'Thabo')
        self.assertEqual(said()[-1], 'Thanks Thabo')

    def test_several_children_become_a_menu(self):
        old = self._old('Menu bot', 'ussd')
        top = self._step(old, 'Top', body_plain='What do you need?')
        jobs = self._step(old, 'Jobs', parent=top, body_plain='Jobs...')
        self._answer(jobs, 'Find a job')
        self._step(old, 'Help', parent=top, body_plain='Help...')
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        self.assertEqual(s['Top'].kind, 'menu')
        options = s['Top'].option_ids.sorted('sequence')
        self.assertEqual(options.mapped('label'), ['Find a job', 'Help'])
        self.assertEqual(options.mapped('next_step_id'), s['Jobs'] | s['Help'])
        self.assertEqual(flow.channel_ids.code, 'ussd')
        self.assertIn('USSD', flow.import_notes)

    def test_numbered_menu_keeps_names_and_numbers(self):
        """A USSD menu answered by number shows the steps' names; a choice
        whose number is not its place (0 for Back) still answers to it."""
        old = self._old('Numbers', 'ussd')
        top = self._step(old, 'Top', body_plain='Please select:')
        for name, number in (('Balance', '1'), ('Bundles', '2'), ('Back', '0')):
            self._answer(self._step(old, name, parent=top, body_plain=name), number)
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        options = s['Top'].option_ids.sorted('sequence')
        self.assertEqual(options.mapped('label'), ['Balance', 'Bundles', 'Back'])
        self.assertEqual(options.mapped('value'), ['1', '2', '0'])
        self.assertIn('number 0', flow.import_notes)
        flow.engine_mode = 'shadow'
        partner = self.env['res.partner'].create({'name': 'Test Contact'})
        Exec = self.env['comm.chatbot.executor']
        c = Exec.start(flow, partner, 'ussd')
        first = c.interaction_ids.filtered(lambda i: i.direction == 'outbound')
        self.assertEqual(first.rendered_body,
                         'Please select:\n\n1. Balance\n2. Bundles\n3. Back')
        Exec._handle_input(c, None, '0')
        self.assertEqual(c.current_step_id, s['Back'])

    def test_buttons_become_choices(self):
        old = self._old('Buttons')
        ask = self._step(old, 'Pick', 'question_interactive',
                         body_plain='Pick one', wa_message_type='interactive_button')
        for seq, title in enumerate(['Yes', 'No']):
            self.env['whatsapp.chatbot.step.button'].create(
                {'step_id': ask.id, 'sequence': seq, 'button_id': title.lower(), 'title': title})
        yes = self._step(old, 'Said yes', parent=ask, body_plain='Great')
        no = self._step(old, 'Said no', parent=ask, body_plain='Pity')
        self._answer(yes, 'yes')
        self._answer(no, 'No')
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        self.assertEqual(s['Pick'].kind, 'menu')
        options = s['Pick'].option_ids.sorted('sequence')
        self.assertEqual(options.mapped('label'), ['Yes', 'No'])
        self.assertEqual(options[0].next_step_id, s['Said yes'])
        self.assertEqual(options[1].next_step_id, s['Said no'])

    def test_variable_rules_become_conditions(self):
        old = self._old('Rules', 'voice')
        var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': old.id, 'name': 'order_number', 'data_type': 'text'})
        top = self._step(old, 'Top', body_plain='Hello')
        known = self._step(old, 'Known', parent=top, body_plain='Found it')
        unknown = self._step(old, 'Unknown', parent=top, body_plain='Which order?')
        Rule = self.env['whatsapp.chatbot.variable.trigger']
        Rule.create({'step_id': known.id, 'variable_id': var.id, 'operator': 'is_set'})
        Rule.create({'step_id': unknown.id, 'variable_id': var.id, 'operator': 'is_not_set'})
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        self.assertEqual(s['Top'].kind, 'message')
        first = s['Top'].next_step_id
        self.assertEqual(first.kind, 'condition')
        self.assertEqual(first.condition_expression, '{{state.order_number}}')
        if_so = first.option_ids.filtered(lambda o: not o.is_default)
        self.assertEqual(if_so.next_step_id, s['Known'])
        second = first.option_ids.filtered('is_default').next_step_id
        self.assertEqual(second.kind, 'condition')
        self.assertEqual(second.option_ids.filtered('is_default').next_step_id, s['Unknown'])

    def test_variable_equal_to_becomes_a_value_condition(self):
        old = self._old('By value')
        var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': old.id, 'name': 'route', 'data_type': 'text'})
        top = self._step(old, 'Top', body_plain='Hello')
        other = self._step(old, 'Other', parent=top, body_plain='Other')
        lead = self._step(old, 'Lead', parent=top, body_plain='Lead')
        self.env['whatsapp.chatbot.variable.trigger'].create(
            {'step_id': lead.id, 'variable_id': var.id,
             'operator': 'is_equal_to', 'value': 'lead'})
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        check = s['Top'].next_step_id
        self.assertEqual((check.kind, check.condition_mode), ('condition', 'equals'))
        named = check.option_ids.filtered(lambda o: not o.is_default)
        self.assertEqual((named.value, named.next_step_id), ('lead', s['Lead']))
        self.assertEqual(check.option_ids.filtered('is_default').next_step_id, s['Other'])

    def test_jump_brings_the_other_bot_and_comes_back(self):
        sub = self._old('Sub')
        sub_var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': sub.id, 'name': 'town', 'data_type': 'text'})
        ask = self._step(sub, 'Ask town', 'question_text', body_plain='Town?')
        self._step(sub, 'Sub done', 'end_flow', ask)
        main = self._old('Main')
        main_var = self.env['whatsapp.chatbot.variable'].create(
            {'chatbot_id': main.id, 'name': 'place', 'data_type': 'text'})
        hello = self._step(main, 'Hello', body_plain='Hi')
        jump = self._step(main, 'Go', 'jump_to_flow', hello,
                          target_chatbot_id=sub.id, jump_mode='subroutine')
        self.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': jump.id, 'source_variable_id': main_var.id,
            'target_variable_id': sub_var.id, 'direction': 'out'})
        self._step(main, 'After', parent=jump, body_plain='Back')

        flow = self.Importer.import_bot(main)
        s = self._by_name(flow)
        other = self.env['comm.bot'].search([('legacy_chatbot_id', '=', sub.id)])
        self.assertEqual(len(other), 1)
        self.assertEqual(s['Go'].kind, 'jump')
        self.assertEqual(s['Go'].jump_target_bot_id, other)
        self.assertTrue(s['Go'].jump_return)
        self.assertEqual(s['Go'].jump_mapping,
                         [{'from': 'place', 'to': 'town', 'direction': 'out'}])
        self.assertEqual(s['Go'].next_step_id, s['After'])
        # Bringing the same bot over again gives the same flow, not a copy.
        self.assertEqual(self.Importer.import_bot(main), flow)
        self.assertEqual(self.Importer.import_bot(sub), other)

    def test_code_and_keywords(self):
        old = self._old('Code bot')
        trigger = self.env['whatsapp.chatbot.trigger'].create(
            {'name': 'MENU', 'chatbot_id': old.id})
        old.bot_trigger_ids = [(4, trigger.id)]
        run = self._step(old, 'Run it', 'execute_code')
        self._step(old, 'Agent', 'transfer_to_agent', run, body_plain='One moment')
        flow = self.Importer.import_bot(old)
        s = self._by_name(flow)
        self.assertEqual(s['Run it'].kind, 'action')
        self.assertFalse(s['Run it'].action_executor)
        self.assertEqual(s['Agent'].kind, 'handoff')
        self.assertEqual(s['Agent'].handoff_message, 'One moment')
        self.assertEqual(flow.trigger_ids.value, 'MENU')
        self.assertIn('ran code', flow.import_notes)
        self.assertIn('MENU', flow.import_notes)

    def test_screen_lists_older_bots(self):
        old = self._old('Listed')
        self._step(old, 'Only', body_plain='Hi')
        Flows = self.env['sediba.flows']
        row = next(b for b in Flows.home()['legacy'] if b['id'] == old.id)
        self.assertEqual((row['steps'], row['flow_id']), (1, False))
        flow_id = Flows.import_legacy(old.id)
        row = next(b for b in Flows.home()['legacy'] if b['id'] == old.id)
        self.assertEqual(row['flow_id'], flow_id)
        self.assertTrue(Flows.load(flow_id)['flow']['notes'])
