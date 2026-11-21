# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSedibaFlows(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flows = cls.env['sediba.flows']
        cls.wa = cls.env.ref('comm_chatbot.channel_whatsapp')
        cls.ussd = cls.env.ref('comm_chatbot.channel_ussd')
        cls.sms = cls.env.ref('comm_chatbot.channel_sms')
        cls.flow_id = cls.Flows.create_flow('Welcome flow')
        cls.bot = cls.env['comm.bot'].browse(cls.flow_id)
        cls.bot.channel_ids = cls.wa | cls.ussd | cls.sms

    def _step(self, data, step_id):
        return next(s for s in data['steps'] if s['id'] == step_id)

    def _menu(self, labels):
        """Turn the first step into a menu with these choices."""
        entry = self.bot.entry_step_id
        return self.Flows.save_step(entry.id, {
            'kind': 'menu',
            'body': 'What do you need?',
            'options': [{'id': False, 'label': label, 'next_id': False}
                        for label in labels],
        })

    def test_new_flow_starts_with_one_step(self):
        self.assertEqual(self.bot.name, 'Welcome flow')
        self.assertEqual(self.bot.engine_mode, 'draft')
        self.assertEqual(len(self.bot.step_ids), 1)
        self.assertEqual(self.bot.entry_step_id, self.bot.step_ids)

    def test_home_lists_flow_and_channels(self):
        home = self.Flows.home()
        row = next(f for f in home['flows'] if f['id'] == self.flow_id)
        self.assertEqual(row['steps'], 1)
        self.assertEqual(set(row['channels']), {'WhatsApp', 'USSD', 'SMS'})
        self.assertIn('ussd', [c['code'] for c in home['channels']])

    def test_add_step_goes_between(self):
        entry = self.bot.entry_step_id
        last = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        middle = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        self.assertEqual(entry.next_step_id.id, middle)
        self.assertEqual(self.env['comm.bot.step'].browse(middle).next_step_id.id, last)
        names = self.bot.step_ids.mapped('name')
        self.assertEqual(len(names), len(set(names)), "step names stay unique")

    def test_menu_comes_out_per_channel(self):
        data = self._menu(['Find a job', 'Build a CV', 'Talk to us'])
        out = self._step(data, self.bot.entry_step_id.id)['out']
        self.assertEqual(out['whatsapp']['options'],
                         ['Find a job', 'Build a CV', 'Talk to us'])
        self.assertIn('3', out['whatsapp']['how'])
        self.assertEqual(out['whatsapp']['body'], 'What do you need?')
        self.assertIn('1. Find a job', out['ussd']['body'])
        self.assertIn('3. Talk to us', out['sms']['body'])
        self.assertEqual(out['ussd']['state'], 'ok')
        self.assertEqual(out['ussd']['limit'], 182)

    def test_too_long_for_ussd_warns(self):
        entry = self.bot.entry_step_id
        data = self.Flows.save_step(entry.id, {'body': 'x' * 200})
        out = self._step(data, entry.id)['out']
        self.assertEqual(out['ussd']['state'], 'warn')
        self.assertIn('200', out['ussd']['note'])
        self.assertEqual(out['whatsapp']['state'], 'ok')

    def test_menu_without_choices_warns(self):
        entry = self.bot.entry_step_id
        data = self.Flows.save_step(entry.id, {'kind': 'menu', 'options': []})
        self.assertEqual(self._step(data, entry.id)['out']['ussd']['state'], 'warn')

    def test_options_update_and_remove(self):
        data = self._menu(['One', 'Two'])
        entry = self.bot.entry_step_id
        rows = self._step(data, entry.id)['options']
        target = self.Flows.add_step(self.flow_id, False, rows[0]['id'])['new_id']
        self.assertEqual(entry.option_ids.sorted('sequence')[0].next_step_id.id, target)
        rows = self._step(self.Flows.load(self.flow_id), entry.id)['options']
        rows[0]['label'] = 'First'
        data = self.Flows.save_step(entry.id, {'options': rows[:1] + [
            {'id': False, 'label': '  ', 'next_id': False}]})
        rows = self._step(data, entry.id)['options']
        self.assertEqual([r['label'] for r in rows], ['First'])
        self.assertEqual(rows[0]['next_id'], target)
        self.assertEqual(entry.option_ids.value, 'First')

    def test_wording_for_one_channel_and_skip(self):
        entry = self.bot.entry_step_id
        data = self.Flows.save_step(entry.id, {
            'body': 'Long welcome',
            'overrides': [
                {'channel_id': self.ussd.id, 'body': 'Hi', 'hide': False},
                {'channel_id': self.sms.id, 'body': '', 'hide': True},
                {'channel_id': self.wa.id, 'body': '', 'hide': False},
            ]})
        out = self._step(data, entry.id)['out']
        self.assertEqual(out['ussd']['body'], 'Hi')
        self.assertEqual(out['whatsapp']['body'], 'Long welcome')
        self.assertEqual(out['sms']['state'], 'skip')
        self.assertEqual(len(entry.channel_override_ids), 2)
        self.Flows.save_step(entry.id, {'overrides': [
            {'channel_id': self.ussd.id, 'body': '', 'hide': False}]})
        self.assertEqual(entry.channel_override_ids.channel_id, self.sms)

    def test_delete_keeps_the_flow_joined(self):
        entry = self.bot.entry_step_id
        last = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        middle = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        data = self.Flows.delete_step(middle)
        self.assertEqual(entry.next_step_id.id, last)
        self.assertEqual(len(data['steps']), 2)
        self.Flows.delete_step(entry.id)
        self.assertEqual(self.bot.entry_step_id.id, last)

    def test_live_flow_keeps_a_first_step(self):
        self.Flows.save_flow(self.flow_id, {'status': 'live'})
        with self.assertRaises(UserError):
            self.Flows.delete_step(self.bot.entry_step_id.id)

    def test_go_live_needs_a_channel(self):
        self.bot.channel_ids = False
        with self.assertRaises(UserError):
            self.Flows.save_flow(self.flow_id, {'status': 'live'})
        data = self.Flows.save_flow(self.flow_id, {'channel_ids': [self.wa.id]})
        self.assertEqual(data['flow']['channel_ids'], [self.wa.id])
        data = self.Flows.save_flow(self.flow_id, {'status': 'live'})
        self.assertEqual(data['flow']['status'], 'live')

    def test_names_cannot_be_empty(self):
        with self.assertRaises(UserError):
            self.Flows.save_step(self.bot.entry_step_id.id, {'name': ' '})
        with self.assertRaises(UserError):
            self.Flows.save_flow(self.flow_id, {'name': ''})

    def test_condition_by_value_is_saved(self):
        entry = self.bot.entry_step_id
        target = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        data = self.Flows.save_step(entry.id, {
            'kind': 'condition', 'condition': '{{state.route}}',
            'condition_mode': 'equals',
            'options': [
                {'id': False, 'label': 'sfm', 'next_id': target},
                {'id': False, 'label': 'Otherwise', 'next_id': False, 'is_default': True},
            ]})
        step = self._step(data, entry.id)
        self.assertEqual(step['condition_mode'], 'equals')
        self.assertEqual([(o['label'], o['is_default']) for o in step['options']],
                         [('sfm', False), ('Otherwise', True)])
        self.assertEqual(entry.option_ids.sorted('sequence')[0].value, 'sfm')

    def _try_flow(self):
        """Welcome by name, then a question whose answer is kept."""
        Var = self.env['comm.bot.variable']
        Var.create({'bot_id': self.bot.id, 'name': 'town', 'type': 'string',
                    'default_value': 'Soweto'})
        Var.create({'bot_id': self.bot.id, 'name': 'age', 'type': 'int'})
        entry = self.bot.entry_step_id
        self.Flows.save_step(entry.id, {
            'body': 'Hi {{contact.first_name}} from {{state.town}}'})
        ask = self.Flows.add_step(self.flow_id, entry.id)['new_id']
        self.Flows.save_step(ask, {'kind': 'input', 'body': 'Age?',
                                   'input_type': 'number', 'save_to': 'age'})
        last = self.Flows.add_step(self.flow_id, ask)['new_id']
        self.Flows.save_step(last, {'body': '{{state.age}} in {{state.town}}'})

    def test_try_it_setup_lists_contact_and_variables(self):
        self._try_flow()
        setup = self.Flows.try_setup(self.flow_id)
        self.assertEqual(setup['name'], 'Test contact')
        group = setup['groups'][0]
        self.assertTrue(group['is_this_flow'])
        self.assertEqual([(v['name'], v['value']) for v in group['variables']],
                         [('age', ''), ('town', 'Soweto')])

    def test_try_it_walk_with_contact_and_variables(self):
        self._try_flow()
        res = self.Flows.try_start(self.flow_id, 'whatsapp', 'Thabo M',
                                   '+27600000009', {'town': 'Durban', 'age': ''})
        self.assertEqual([m['body'] for m in res['messages']],
                         ['Hi Thabo from Durban', 'Age?'])
        self.assertEqual(res['waiting'], 'input')
        self.assertEqual(res['variables'], {'town': 'Durban'})
        # Change a variable in the middle of the walk, then answer.
        res = self.Flows.try_apply(res['session_id'], 'Thabo M', '+27600000009',
                                   {'town': 'Pretoria'})
        res = self.Flows.try_reply(res['session_id'], '31')
        self.assertEqual(res['messages'][-1]['body'], '31 in Pretoria')
        self.assertEqual(res['variables'], {'town': 'Pretoria', 'age': '31'})
        # The test contact is this user's own, archived, and reused.
        contact = self.env['res.partner'].with_context(active_test=False).search(
            [('ref', '=', 'sediba-flows-try-%s' % self.env.uid)])
        self.assertEqual((len(contact), contact.active, contact.name),
                         (1, False, 'Thabo M'))
        self.assertEqual(self.Flows.try_setup(self.flow_id)['name'], 'Thabo M')
        self.Flows.try_stop(res['session_id'])
        self.assertFalse(self.env['comm.conversation'].browse(
            int(res['session_id'])).exists())

    def test_try_it_never_touches_a_real_conversation(self):
        partner = self.env['res.partner'].create({'name': 'Real person'})
        real = self.env['comm.conversation'].create({
            'partner_id': partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.wa.id,
            'current_step_id': self.bot.entry_step_id.id})
        self.assertIn('error', self.Flows.try_reply(real.id, 'hello'))
        self.assertIn('error', self.Flows.try_apply(real.id, 'X', '', {'a': 'b'}))
        self.Flows.try_stop(real.id)
        self.assertTrue(real.exists())
        self.assertEqual(partner.name, 'Real person')

    def test_dragged_card_is_kept_and_tidied(self):
        entry = self.bot.entry_step_id
        self.assertFalse(self._step(self.Flows.load(self.flow_id), entry.id)['placed'])
        self.Flows.move_step(entry.id, 340, -5)
        step = self._step(self.Flows.load(self.flow_id), entry.id)
        self.assertEqual((step['placed'], step['x'], step['y']), (True, 340, 0))
        step = self._step(self.Flows.tidy(self.flow_id), entry.id)
        self.assertFalse(step['placed'])

    def test_usage_counts_contacts_not_tests(self):
        self._try_flow()
        entry = self.bot.entry_step_id
        data = self.Flows.load(self.flow_id)
        self.assertEqual(data['flow']['reached_most'], 0)
        # A walk in Try it does not count.
        res = self.Flows.try_start(self.flow_id, 'whatsapp', 'Tester', '', {})
        self.assertEqual(self.Flows.load(self.flow_id)['flow']['reached_most'], 0)
        # Two real contacts start; one of them answers the question.
        self.bot.engine_mode = 'shadow'
        Exec = self.env['comm.chatbot.executor']
        people = self.env['res.partner'].create([{'name': 'One'}, {'name': 'Two'}])
        talks = [Exec.start(self.bot, p, 'whatsapp') for p in people]
        Exec._handle_input(talks[0], None, '30')
        data = self.Flows.load(self.flow_id)
        by_name = {s['name']: s['reached'] for s in data['steps']}
        self.assertEqual(data['flow']['reached_most'], 2)
        self.assertEqual(by_name[entry.name], 2)
        self.assertEqual(sorted(by_name.values()), [1, 2, 2])
        self.Flows.try_stop(res['session_id'])

    def test_device_preview_needs_the_web_chat_addon(self):
        url = self.Flows.load(self.flow_id)['flow']['device_url']
        if 'comm.bot.web.session' in self.env:
            self.assertEqual(url, '/comm_chatbot_web/embed/%s?preview=1' % self.flow_id)
        else:
            self.assertEqual(url, '')

    def test_header_footer_and_image(self):
        self.wa.supports_header_footer = True
        entry = self.bot.entry_step_id
        data = self.Flows.save_step(entry.id, {
            'body': 'Welcome', 'header': 'Hi {{contact.first_name}}',
            'footer': 'Reply STOP to leave',
            'image_url': 'https://example.com/logo.png', 'image_alt': 'Our logo'})
        step = self._step(data, entry.id)
        self.assertEqual((step['header'], step['footer'], step['image_url'], step['image_alt']),
                         ('Hi {{contact.first_name}}', 'Reply STOP to leave',
                          'https://example.com/logo.png', 'Our logo'))
        first = self.env.user.partner_id.name.split(' ')[0]
        wa, ussd = step['out']['whatsapp'], step['out']['ussd']
        self.assertEqual((wa['header'], wa['body'], wa['footer'], wa['image']),
                         ('Hi %s' % first, 'Welcome', 'Reply STOP to leave',
                          'https://example.com/logo.png'))
        # USSD has no header, footer or pictures: all of it is in the text.
        self.assertEqual((ussd['header'], ussd['footer'], ussd['image']), ('', '', ''))
        self.assertEqual(ussd['body'],
                         'Hi %s\nWelcome\nOur logo\nReply STOP to leave' % first)
        # Taking the address away removes the image.
        data = self.Flows.save_step(entry.id, {'image_url': ''})
        self.assertFalse(entry.media_ids)
        self.assertEqual(self._step(data, entry.id)['out']['whatsapp']['image'], '')

    def test_try_it_shows_header_and_footer_where_the_channel_does(self):
        self.wa.supports_header_footer = True
        self.Flows.save_step(self.bot.entry_step_id.id, {
            'body': 'Welcome', 'header': 'Hello', 'footer': 'Bye'})
        on_wa = self.Flows.try_start(self.flow_id, 'whatsapp', 'T', '', {})['messages'][0]
        self.assertEqual((on_wa['header'], on_wa['body'], on_wa['footer']),
                         ('Hello', 'Welcome', 'Bye'))
        on_ussd = self.Flows.try_start(self.flow_id, 'ussd', 'T', '', {})['messages'][0]
        self.assertEqual((on_ussd['header'], on_ussd['body'], on_ussd['footer']),
                         ('', 'Hello\nWelcome\nBye', ''))

    def test_long_whatsapp_button_is_flagged(self):
        entry = self.bot.entry_step_id
        data = self.Flows.save_step(entry.id, {
            'kind': 'menu', 'body': 'Pick',
            'options': [{'id': False, 'label': 'A label longer than twenty characters', 'next_id': False}]})
        out = self._step(data, entry.id)['out']
        self.assertEqual(out['whatsapp']['state'], 'warn')
        self.assertIn('20', out['whatsapp']['note'])
        self.assertEqual(out['ussd']['state'], 'ok')
