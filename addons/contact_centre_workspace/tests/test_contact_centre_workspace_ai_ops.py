# -*- coding: utf-8 -*-
"""The AI Ops section of the workspace: the copilot chats, one chat with what
the copilot did, and who may use it. Needs contact_centre_ai_ops; skipped
without it.

Nothing here talks to the AI service: the one message that is sent goes out
with no API key set and with the network call replaced by one that fails the
test if it is ever reached."""

from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

CHAT = 'contact.centre.ai.chat'


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceAiOps(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_ai_agent', groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.manager = new_test_user(cls.env, 'ccw_ai_manager', groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.other = new_test_user(cls.env, 'ccw_ai_other', name='Zzq Other Manager',
                                  groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.Boss = cls.env['contact.centre.workspace'].with_user(cls.manager)

    def setUp(self):
        super().setUp()
        if CHAT not in self.env:
            self.skipTest("contact_centre_ai_ops is not installed")

    def _chat(self, name, user=None, **vals):
        return self.env[CHAT].create(dict({'name': name, 'user_id': (user or self.manager).id}, **vals))

    def _say(self, chat, role, content, **vals):
        return self.env['contact.centre.ai.chat.message'].create(dict(
            {'session_id': chat.id, 'role': role, 'content': content}, **vals))

    def _did(self, chat, tool, result, success=True, **tool_input):
        return self.env['contact.centre.ai.chat.action'].create({
            'session_id': chat.id, 'tool_name': tool, 'tool_input': tool_input, 'tool_result': result, 'success': success})

    def test_managers_only(self):
        chat = self._chat('Zzq Renewals')
        self.assertFalse(self.Ws.ws_boot()['ai_ops'])
        self.assertTrue(self.Boss.ws_boot()['ai_ops'])
        for attempt in (self.Ws.ws_ai_chats, self.Ws.ws_ai_new_chat, lambda: self.Ws.ws_ai_chat(chat.id),
                        lambda: self.Ws.ws_ai_rename(chat.id, 'X')):
            with self.assertRaises(AccessError):
                attempt()

    def test_chats(self):
        renewals = self._chat('Zzq Renewals')
        self._say(renewals, 'user', 'Draft a renewal campaign')
        self._say(renewals, 'assistant', 'Here is the **plan**.\n\n- `Shall` I go ahead?')
        welcome = self._chat('Zzq Welcome', user=self.other)
        self._say(welcome, 'assistant', 'Hello')
        self._say(welcome, 'user', 'Find the zzqwelcome wording')
        empty = self._chat('Zzq Empty')
        # The copilot is holding a change in this one until someone says yes.
        renewals.pending_state = {'messages': [], 'results': [], 'held': [
            {'id': 'toolu_1', 'name': 'create_campaign', 'input': {'name': 'November renewals'}}]}

        result = self.Boss.ws_ai_chats(search='zzq')
        rows = {row['id']: row for row in result['rows']}
        self.assertEqual((result['total'], result['more'], set(rows)), (3, False, {renewals.id, welcome.id, empty.id}))
        row = rows[renewals.id]
        self.assertEqual((row['name'], row['preview'], row['mine_last'], row['waiting'], row['by']),
                         ('Zzq Renewals', 'Here is the plan. Shall I go ahead?', False, True, ''))
        row = rows[welcome.id]
        self.assertEqual((row['preview'], row['mine_last'], row['waiting'], row['by']),
                         ('Find the zzqwelcome wording', True, False, 'Zzq Other Manager'))
        self.assertEqual((rows[empty.id]['preview'], rows[empty.id]['waiting']), ('', False))

        # What was said is searched too.
        self.assertEqual([r['id'] for r in self.Boss.ws_ai_chats(search='zzqwelcome wording')['rows']], [welcome.id])
        page = self.Boss.ws_ai_chats(search='zzq', limit=2)
        self.assertEqual((len(page['rows']), page['more']), (2, True))
        self.assertEqual(len(self.Boss.ws_ai_chats(search='zzq', limit=2, offset=2)['rows']), 1)

    def test_one_chat(self):
        chat = self._chat('Zzq Renewals')
        self._say(chat, 'user', 'Draft a renewal campaign')
        self._say(chat, 'assistant', '**Done.** What next?', suggestions=['Add contacts', 'Nothing else'])
        self._did(chat, 'list_templates', {'templates': []})
        self._did(chat, 'create_campaign', {'campaign_id': 7, 'name': 'November renewals'}, name='November renewals')
        self._did(chat, 'update_campaign', {'error': 'No such template'}, success=False, campaign_id=7)
        self._did(chat, 'delete_dashboard_card', {'declined': True, 'note': 'The user declined this action.'}, success=False, card_id=3)
        chat.pending_state = {'held': [{'id': 'toolu_2', 'name': 'update_template', 'input': {'template_id': 4}}]}

        data = self.Boss.ws_ai_chat(chat.id)
        self.assertEqual((data['name'], data['by']), ('Zzq Renewals', ''))
        self.assertEqual([(m['mine'], m['content'], m['suggestions']) for m in data['messages']],
                         [(True, 'Draft a renewal campaign', []), (False, '**Done.** What next?', ['Add contacts', 'Nothing else'])])
        self.assertEqual([(a['tool'], a['ok'], a['declined']) for a in data['actions']],
                         [('list_templates', True, False), ('create_campaign', True, False),
                          ('update_campaign', False, False), ('delete_dashboard_card', False, True)])
        self.assertEqual((data['actions'][1]['input'], data['actions'][1]['result']['campaign_id']), ({'name': 'November renewals'}, 7))
        self.assertEqual(data['held'], [{'tool': 'update_template', 'input': {'template_id': 4}}])
        # Another manager sees who started it.
        self.assertEqual(self.env['contact.centre.workspace'].with_user(self.other).ws_ai_chat(chat.id)['by'], self.manager.name)
        with self.assertRaises(UserError):
            self.Boss.ws_ai_chat(0)

    def test_new_chat_and_rename(self):
        chat = self.env[CHAT].browse(self.Boss.ws_ai_new_chat())
        self.assertEqual((chat.name, chat.user_id), ('New chat', self.manager))
        data = self.Boss.ws_ai_chat(chat.id)
        self.assertEqual((data['messages'], data['actions'], data['held']), ([], [], []))
        self.assertEqual(self.Boss.ws_ai_rename(chat.id, '  Zzq  Renewal plans '), 'Zzq Renewal plans')
        self.assertEqual(chat.name, 'Zzq Renewal plans')
        with self.assertRaises(UserError):
            self.Boss.ws_ai_rename(chat.id, '   ')

    def test_sending_without_a_key_never_reaches_the_ai(self):
        """The section sends through the copilot's own send_message. With no
        key set it answers by itself, and the chat shows both messages."""
        self.env['ir.config_parameter'].sudo().set_param('whatsapp.anthropic_api_key', False)
        chat = self.env[CHAT].browse(self.Boss.ws_ai_new_chat())
        with patch('requests.post', side_effect=AssertionError("the AI service must not be called in a test")):
            chat.with_user(self.manager).send_message('Draft a renewal campaign')
        data = self.Boss.ws_ai_chat(chat.id)
        self.assertEqual([m['mine'] for m in data['messages']], [True, False])
        self.assertIn("API key isn't configured", data['messages'][1]['content'])
        self.assertEqual(self.Boss.ws_ai_chats(search='Draft a renewal campaign')['rows'][0]['id'], chat.id)
