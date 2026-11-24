# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter


@tagged('post_install', '-at_install')
class TestFlowEmailAddress(TransactionCase):
    """A flow is connected to one email address: mail to it starts the flow,
    and the flow replies in the same email thread. No mail leaves the tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.domain = cls.env['mail.alias.domain'].search([('name', '=', 'flows.test')]) \
            or cls.env['mail.alias.domain'].create({'name': 'flows.test'})
        cls.env.company.alias_domain_id = cls.domain
        cls.channel = cls.env.ref('comm_chatbot_email.channel_email')
        cls.Thread = cls.env['comm.bot.email.thread']
        cls.adapter = get_adapter('email')()
        cls.bot = cls._flow('Sign up')

    @classmethod
    def _flow(cls, name, mode='live'):
        """Welcome, ask a name, thank them by it."""
        Step = cls.env['comm.bot.step']
        bot = cls.env['comm.bot'].create({'name': name, 'channel_ids': [(6, 0, cls.channel.ids)]})
        thanks = Step.create({'bot_id': bot.id, 'name': 'Thanks', 'kind': 'message',
                              'body': 'Thanks {{state.name}}'})
        ask = Step.create({'bot_id': bot.id, 'name': 'Ask', 'kind': 'input', 'body': 'Your name?',
                           'input_type': 'text', 'input_save_to': 'name', 'next_step_id': thanks.id})
        hello = Step.create({'bot_id': bot.id, 'name': 'Hello', 'kind': 'message',
                             'body': 'Welcome', 'next_step_id': ask.id})
        bot.write({'entry_step_id': hello.id, 'engine_mode': mode})
        return bot

    def _mail(self, body, subject='Hi', sender='Thandi <thandi@example.com>'):
        return {'email_from': sender, 'subject': subject, 'body': body,
                'message_id': '<%s@example.com>' % abs(hash((body, subject)))}

    def _said(self, thread):
        """What the flow wrote back on the thread, oldest first."""
        return [m.body for m in thread.message_ids.sorted('id') if m.message_type == 'comment']

    # ── Connecting ───────────────────────────────────────────────────────

    def test_a_new_address_is_made_and_connected(self):
        self.assertFalse(self.adapter.connections(self.env, self.bot)[0]['ok'])
        self.adapter.connect_new(self.env, self.bot, ' Jobs@whatever.example ')
        alias = self.bot.email_alias_id
        self.assertEqual(alias.alias_full_name, 'jobs@flows.test')
        self.assertEqual(alias.alias_model_id.model, 'comm.bot.email.thread')
        self.assertEqual(alias.alias_defaults, repr({'bot_id': self.bot.id}))
        first = self.adapter.connections(self.env, self.bot)[0]
        self.assertEqual((first['name'], first['model'], first['option_id']),
                         ('jobs@flows.test', 'mail.alias', alias.id))
        for bad in ('', 'has space', 'ü', '-x'):
            with self.assertRaises(UserError):
                self.adapter.connect_new(self.env, self.bot, bad)

    def test_one_address_starts_one_flow(self):
        other = self._flow('Other')
        self.adapter.connect_new(self.env, self.bot, 'jobs')
        alias = self.bot.email_alias_id
        option = next(o for o in self.adapter.connect_options(self.env, other) if o['id'] == alias.id)
        self.assertEqual((option['connected'], option['runs']), (False, 'Sign up'))
        self.adapter.connect(self.env, other, alias.id, True)
        self.assertEqual(other.email_alias_id, alias)
        self.assertFalse(self.bot.email_alias_id, "taken off the flow it was on")
        self.assertEqual(alias.alias_defaults, repr({'bot_id': other.id}))
        self.adapter.connect(self.env, other, alias.id, False)
        self.assertFalse(other.email_alias_id)
        self.assertEqual(alias.alias_defaults, '{}', "kept, but starts nothing")

    def test_an_address_something_else_uses_is_listed_but_not_taken(self):
        foreign = self.env['mail.alias'].create({
            'alias_name': 'partners-inbox', 'alias_domain_id': self.domain.id,
            'alias_model_id': self.env['ir.model']._get('res.partner').id})
        option = next(o for o in self.adapter.connect_options(self.env, self.bot)
                      if o['id'] == foreign.id)
        self.assertTrue(option['disabled'])
        self.assertIn('used by', option['note'])
        with self.assertRaises(UserError):
            self.adapter.connect(self.env, self.bot, foreign.id, True)
        self.assertEqual(foreign.alias_model_id.model, 'res.partner')

    def test_missing_servers_are_said(self):
        self.env['ir.mail_server'].search([]).write({'active': False})
        self.env['fetchmail.server'].search([]).write({'active': False})
        self.adapter.connect_new(self.env, self.bot, 'jobs')
        texts = ' '.join(line['text'] for line in self.adapter.connections(self.env, self.bot))
        self.assertIn('No incoming mail server', texts)
        self.assertIn('No outgoing mail server', texts)
        server = self.env['ir.mail_server'].create({'name': 'Test SMTP', 'smtp_host': 'smtp.invalid'})
        sent_by = next(line for line in self.adapter.connections(self.env, self.bot)
                       if line.get('label') == 'Sent by')
        self.assertEqual((sent_by['name'], sent_by['res_id']), ('Test SMTP', server.id))

    def test_a_copy_has_no_address(self):
        self.adapter.connect_new(self.env, self.bot, 'jobs')
        self.assertFalse(self.bot.copy({'name': 'Sign up two'}).email_alias_id)

    # ── Mail coming in ───────────────────────────────────────────────────

    def test_a_mail_starts_the_flow_and_a_reply_carries_it_on(self):
        self.adapter.connect_new(self.env, self.bot, 'jobs')
        thread = self.Thread.message_new(self._mail('<p>Hello there</p>'),
                                         custom_values={'bot_id': self.bot.id})
        self.assertEqual(thread.partner_id.email, 'thandi@example.com')
        conversation = thread.conversation_id
        self.assertEqual((conversation.bot_id, conversation.current_step_id.name),
                         (self.bot, 'Ask'))
        said = self._said(thread)
        self.assertEqual(len(said), 2)
        self.assertIn('Welcome', said[0])
        self.assertIn('Your name?', said[1])
        sent = thread.message_ids.filtered(lambda m: m.message_type == 'comment')[0]
        self.assertIn('jobs@flows.test', sent.email_from)
        self.assertIn('jobs@flows.test', sent.reply_to)
        self.assertEqual(sent.partner_ids, thread.partner_id)

        # The reply, with the earlier mail quoted under it as mail programs do.
        thread.message_update(self._mail(
            '<p>Thandi</p><p>On Mon, 1 Jan 2026 at 10:00, Company wrote:</p>'
            '<blockquote>Your name?</blockquote>', subject='Re: Hi'))
        self.assertEqual(conversation.state.get('name'), 'Thandi')
        self.assertIn('Thanks Thandi', self._said(thread)[-1])

    def test_a_flow_that_is_not_live_keeps_the_mail_and_says_nothing(self):
        draft = self._flow('Draft one', mode='draft')
        thread = self.Thread.message_new(self._mail('<p>Hello</p>'),
                                         custom_values={'bot_id': draft.id})
        self.assertTrue(thread.exists())
        self.assertFalse(thread.conversation_id)
        self.assertEqual(self._said(thread), [])

    def test_an_address_no_flow_is_on_keeps_the_mail(self):
        thread = self.Thread.message_new(self._mail('<p>Hello</p>'), custom_values={})
        self.assertTrue(thread.exists())
        self.assertEqual(self._said(thread), [])

    def test_only_what_was_typed_is_the_answer(self):
        text = self.Thread._reply_text(
            '<div>Yes please</div><div>&gt; Do you want a call?</div><div>&gt; Reply yes or no</div>')
        self.assertEqual(text, 'Yes please')
        self.assertEqual(self.Thread._reply_text('<p>2</p><p>Sent from my phone</p>'), '2')
        self.assertEqual(self.Thread._reply_text(
            '<div>Jobs</div><blockquote type="cite"><div>Which one?</div></blockquote>'), 'Jobs')
        self.assertEqual(self.Thread._reply_text('<div>line one</div><div>line two</div>'),
                         'line one\nline two')
        self.assertEqual(self.Thread._reply_text(''), '')

    def test_two_auto_responders_do_not_write_for_ever(self):
        from odoo.addons.comm_chatbot_email.models.comm_bot_email_thread import MAX_INBOUND
        thread = self.Thread.message_new(self._mail('<p>Hello</p>'),
                                         custom_values={'bot_id': self.bot.id})
        thread.inbound_count = MAX_INBOUND
        before = len(self._said(thread))
        thread.message_update(self._mail('<p>I am out of office</p>', subject='Auto'))
        self.assertEqual(len(self._said(thread)), before)
