# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

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

    def test_card_says_what_the_flow_is_and_where_it_runs(self):
        self.Flows.save_flow(self.flow_id, {'description': '  Signs people up.  '})
        self.assertEqual(self.bot.description, 'Signs people up.')
        card = next(f for f in self.Flows.home()['flows'] if f['id'] == self.flow_id)
        self.assertEqual(card['description'], 'Signs people up.')
        self.assertEqual(set(card['channel_codes']), {'whatsapp', 'ussd', 'sms'})
        self.assertEqual({r['channel'] for r in card['runs']}, {'WhatsApp', 'USSD', 'SMS'})
        self.assertTrue(card['edited'])
        # Nobody has talked to it, so there are no numbers to show.
        self.assertFalse(card['usage'])
        self.assertEqual(card['attention'], [])
        self.assertEqual(self.Flows.load(self.flow_id)['flow']['description'], 'Signs people up.')

    def test_card_flags_an_empty_action(self):
        self.env['comm.bot.step'].create({
            'bot_id': self.bot.id, 'name': 'Look it up', 'kind': 'action'})
        card = next(f for f in self.Flows.home()['flows'] if f['id'] == self.flow_id)
        self.assertEqual(card['attention'], ['1 step runs an action that is empty'])

    def test_card_numbers_count_contacts_not_tests(self):
        self._try_flow()
        res = self.Flows.try_start(self.flow_id, 'whatsapp', 'Tester', '', {})
        card = next(f for f in self.Flows.home()['flows'] if f['id'] == self.flow_id)
        self.assertFalse(card['usage'], "a walk in Try it is not a conversation")
        self.bot.engine_mode = 'shadow'
        Exec = self.env['comm.chatbot.executor']
        people = self.env['res.partner'].create(
            [{'name': 'One'}, {'name': 'Two'}, {'name': 'Three'}])
        talks = [Exec.start(self.bot, p, 'whatsapp') for p in people]
        stopped_at = talks[1].current_step_id
        # One of them reaches the end; one started long ago.
        talks[0].close(outcome='ended', state='closed')
        talks[2].opened_at = talks[2].opened_at - timedelta(days=45)
        usage = next(f for f in self.Flows.home()['flows'] if f['id'] == self.flow_id)['usage']
        self.assertEqual(usage['conversations'], 2)
        self.assertEqual(usage['finished_pct'], 50)
        self.assertEqual(len(usage['days']), 14)
        self.assertEqual(usage['days'][-1], 2)
        self.assertEqual(sum(usage['days']), 2)
        self.assertEqual(usage['stop'], stopped_at.name)
        self.Flows.try_stop(res['session_id'])

    def test_duplicate_copies_the_flow_and_connects_nothing(self):
        data = self._menu(['Jobs', 'Help'])
        entry = self.bot.entry_step_id
        jobs = self.Flows.add_step(self.flow_id, entry.id, data['steps'][0]['options'][0]['id'])
        self.Flows.save_step(jobs['new_id'], {'body': 'Jobs near you', 'name': 'Jobs'})
        self.Flows.save_step(entry.id, {'overrides': [
            {'channel_id': self.ussd.id, 'body': 'Short', 'hide': False}]})
        self.Flows.set_image(entry.id, 'logo.png', self.PNG)
        self.Flows.move_step(entry.id, 300, 120)
        self.env['comm.bot.variable'].create(
            {'bot_id': self.bot.id, 'name': 'town', 'type': 'string'})
        self.env['comm.bot.trigger'].create(
            {'bot_id': self.bot.id, 'channel_id': self.wa.id,
             'kind': 'keyword', 'value': 'JOBS'})
        self.bot.write({'description': 'Finds jobs', 'engine_mode': 'shadow'})
        self.env['comm.chatbot.executor'].start(
            self.bot, self.env['res.partner'].create({'name': 'One'}), 'whatsapp')
        steps_before = len(self.bot.step_ids)

        copy = self.env['comm.bot'].browse(
            self.Flows.duplicate_flow(self.flow_id, '  Jobs v2  '))
        self.assertEqual((copy.name, copy.engine_mode), ('Jobs v2', 'draft'))
        self.assertEqual(copy.description, 'Finds jobs')
        self.assertEqual(copy.channel_ids, self.bot.channel_ids)
        self.assertEqual(copy.variable_ids.mapped('name'), ['town'])
        # Every link stays inside the copy.
        self.assertEqual(len(copy.step_ids), steps_before)
        self.assertFalse(copy.step_ids & self.bot.step_ids)
        first = copy.entry_step_id
        self.assertIn(first, copy.step_ids)
        self.assertEqual(first.name, entry.name)
        self.assertEqual(first.option_ids.mapped('label'), ['Jobs', 'Help'])
        target = first.option_ids[0].next_step_id
        self.assertEqual((target.bot_id, target.name), (copy, 'Jobs'))
        self.assertEqual(first.channel_override_ids.body_override, 'Short')
        self.assertEqual((first.flow_placed, first.flow_x, first.flow_y), (True, 300, 120))
        # Its own copy of the picture: taking it off one leaves the other.
        self.assertTrue(first.media_ids.attachment_id)
        self.assertNotEqual(first.media_ids.attachment_id, entry.media_ids.attachment_id)
        self.Flows.remove_image(first.id)
        self.assertTrue(entry.media_ids.attachment_id.exists())
        # Nothing is connected, and nobody has talked to it.
        self.assertFalse(copy.trigger_ids)
        card = next(f for f in self.Flows.home()['flows'] if f['id'] == copy.id)
        self.assertFalse(card['usage'])
        # The original is as it was.
        self.assertEqual(self.bot.engine_mode, 'shadow')
        self.assertEqual(self.bot.trigger_ids.value, 'JOBS')
        self.assertEqual(len(self.bot.step_ids), steps_before)
        self.assertEqual(self.bot.entry_step_id, entry)

    def test_duplicate_gets_a_name_when_none_is_given(self):
        copy = self.env['comm.bot'].browse(self.Flows.duplicate_flow(self.flow_id))
        self.assertEqual(copy.name, 'Welcome flow (copy)')

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

    # A 1x1 PNG.
    PNG = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGA'
           'WjR9awAAAABJRU5ErkJggg==')

    def test_upload_a_picture(self):
        entry = self.bot.entry_step_id
        data = self.Flows.set_image(entry.id, 'logo.png', self.PNG)
        step = self._step(data, entry.id)
        attachment = entry.media_ids.attachment_id
        self.assertTrue(attachment.public, "WhatsApp fetches it by address")
        self.assertEqual((step['image_file'], step['image_url']), ('logo.png', ''))
        self.assertEqual(step['image_src'], '/web/image/%s' % attachment.id)
        self.assertEqual(step['out']['whatsapp']['image'], step['image_src'])
        self.assertEqual(step['out']['ussd']['image'], '')
        # Saving the step's other fields keeps the uploaded picture.
        data = self.Flows.save_step(entry.id, {
            'body': 'Hello', 'image_url': '', 'image_alt': 'Our logo'})
        self.assertEqual(entry.media_ids.attachment_id, attachment)
        self.assertEqual(entry.media_ids.alt_text, 'Our logo')
        # A new upload replaces the old file; removing it leaves nothing.
        self.Flows.set_image(entry.id, 'new.png', self.PNG)
        self.assertFalse(attachment.exists())
        self.assertEqual(len(entry.media_ids), 1)
        data = self.Flows.remove_image(entry.id)
        self.assertFalse(entry.media_ids)
        self.assertEqual(self._step(data, entry.id)['image_src'], '')

    def test_upload_refuses_what_is_not_a_picture(self):
        import base64
        entry = self.bot.entry_step_id
        with self.assertRaises(UserError):
            self.Flows.set_image(entry.id, 'notes.txt',
                                 base64.b64encode(b'just some text').decode())
        self.assertFalse(entry.media_ids)

    def test_connections_say_what_is_and_is_not_connected(self):
        data = self.Flows.load(self.flow_id)
        by_channel = {c['channel_id']: c['lines'] for c in data['flow']['connections']}
        self.assertEqual(set(by_channel), set(self.bot.channel_ids.ids))
        for lines in by_channel.values():
            self.assertTrue(lines)
            self.assertTrue(all(line['text'] and 'ok' in line for line in lines))

    def test_an_account_line_can_be_opened_when_it_may_be_read(self):
        partner = self.env['res.partner'].create({'name': 'Stands in for an account'})
        account = {'ok': True, 'text': 'Sends from it.', 'name': 'Main line',
                   'address': '+27 10 000 0000', 'model': 'res.partner', 'res_id': partner.id}
        line = self.Flows._connection_line(account)
        self.assertTrue(line['account'])
        self.assertEqual((line['model'], line['res_id']), ('res.partner', partner.id))
        # A record that is gone, or a kind of record that does not exist here,
        # is still named but cannot be opened.
        gone = self.Flows._connection_line(dict(account, res_id=partner.id + 100000))
        self.assertTrue(gone['account'])
        self.assertNotIn('model', gone)
        self.assertNotIn('res_id', gone)
        self.assertNotIn('model', self.Flows._connection_line(dict(account, model='no.such.model')))
        # What starts a flow is not an account, and a warning is neither.
        self.assertFalse(self.Flows._connection_line(
            {'ok': True, 'text': 'x', 'name': 'Starts on', 'address': 'JOBS'})['account'])
        self.assertFalse(self.Flows._connection_line({'ok': False, 'text': 'Nothing.'})['account'])

    def test_card_names_the_accounts_only(self):
        partner = self.env['res.partner'].create({'name': 'Stands in for an account'})
        lines = [
            {'ok': True, 'text': 's', 'name': 'Main line', 'address': '+27 10 000 0000',
             'model': 'res.partner', 'res_id': partner.id},
            {'ok': True, 'text': 's', 'name': 'Starts on', 'address': 'JOBS'},
            {'ok': False, 'text': 'A warning.'},
        ]
        connections = [
            {'channel_id': self.wa.id, 'options': [],
             'lines': [self.Flows._connection_line(line) for line in lines]},
            {'channel_id': self.sms.id, 'options': [],
             'lines': [{'ok': False, 'text': 'Nothing.', 'account': False}]},
        ]
        with patch.object(type(self.Flows), '_connections', lambda self, bot: connections):
            runs = {r['channel']: r for r in self.Flows._card_runs(self.bot)}
        self.assertEqual(runs['WhatsApp']['links'], [{
            'name': 'Main line', 'address': '+27 10 000 0000',
            'model': 'res.partner', 'res_id': partner.id}])
        self.assertTrue(runs['WhatsApp']['ok'])
        self.assertEqual((runs['SMS']['ok'], runs['SMS']['links']), (False, []))

    def _keyword_adapter(self):
        """Stands in for a channel add-on whose flows start on a keyword."""
        class Keyworded:
            keyword_start = True
            connect_noun = 'number'

            def connections(self, env, bot):
                return [{'ok': False, 'text': 'Nothing connected.'}]
        return patch('odoo.addons.sediba_flows.models.sediba_flows.get_adapter',
                     lambda key: Keyworded)

    def _keywords(self, data, channel):
        return next(c for c in data['flow']['connections']
                    if c['channel_id'] == channel.id)['keywords']

    def test_keywords_are_added_once_and_removed(self):
        with self._keyword_adapter():
            data = self.Flows.add_keyword(self.flow_id, self.wa.id, '  Jobs  ')
            self.assertEqual(self._keywords(data, self.wa), {'words': ['Jobs'], 'any': False})
            self.assertEqual(next(c for c in data['flow']['connections']
                                  if c['channel_id'] == self.wa.id)['noun'], 'number')
            # The same word again, in other capitals, is not added twice.
            data = self.Flows.add_keyword(self.flow_id, self.wa.id, 'JOBS')
            self.assertEqual(self._keywords(data, self.wa)['words'], ['Jobs'])
            trigger = self.bot.trigger_ids
            self.assertEqual((trigger.kind, trigger.match_mode, trigger.channel_id),
                             ('keyword', 'exact', self.wa))
            with self.assertRaises(UserError):
                self.Flows.add_keyword(self.flow_id, self.wa.id, '   ')
            data = self.Flows.remove_keyword(self.flow_id, self.wa.id, 'jobs')
            self.assertEqual(self._keywords(data, self.wa)['words'], [])

    def test_a_keyword_starts_one_flow_only(self):
        other = self.env['comm.bot'].browse(self.Flows.create_flow('Other flow'))
        with self._keyword_adapter():
            self.Flows.add_keyword(other.id, self.wa.id, 'Jobs')
            with self.assertRaises(UserError) as error:
                self.Flows.add_keyword(self.flow_id, self.wa.id, 'jobs')
            self.assertIn('Other flow', str(error.exception))
            # The same word on another channel is its own thing.
            self.Flows.add_keyword(self.flow_id, self.sms.id, 'jobs')
            self.assertEqual(self.bot.trigger_ids.channel_id, self.sms)

    def test_only_one_flow_takes_any_message(self):
        other = self.env['comm.bot'].browse(self.Flows.create_flow('Other flow'))
        with self._keyword_adapter():
            data = self.Flows.set_any_message(self.flow_id, self.wa.id, True)
            self.assertTrue(self._keywords(data, self.wa)['any'])
            with self.assertRaises(UserError):
                self.Flows.set_any_message(other.id, self.wa.id, True)
            data = self.Flows.set_any_message(self.flow_id, self.wa.id, False)
            self.assertFalse(self._keywords(data, self.wa)['any'])
            self.Flows.set_any_message(other.id, self.wa.id, True)

    def test_keywords_only_where_the_channel_starts_flows_that_way(self):
        data = self.Flows.load(self.flow_id)
        if not self._keywords(data, self.ussd):
            with self.assertRaises(UserError):
                self.Flows.add_keyword(self.flow_id, self.ussd.id, 'Jobs')

    def test_connect_channel_needs_something_to_connect(self):
        class Fixed:
            """A channel add-on with one fixed connection and no choice."""
            def connections(self, env, bot):
                return [{'ok': True, 'text': 'Always on.'}]
        with patch('odoo.addons.sediba_flows.models.sediba_flows.get_adapter',
                   lambda key: Fixed), self.assertRaises(UserError):
            self.Flows.connect_channel(self.flow_id, self.wa.id, 1, True)
        data = self.Flows.load(self.flow_id)
        self.assertTrue(all('options' in c for c in data['flow']['connections']))
