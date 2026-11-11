# -*- coding: utf-8 -*-
"""The sidekick only answers: its lists are the server's, its chats are the
agent's own, and nothing personal beyond first names reaches the AI. ID checks
on the Candidates filters and the candidate card are for staff who may run them."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'
AI = 'odoo.addons.chat2work_workspace.models.chat2work_sidekick._ai_json'
ID_NO = '9111060123086'


def said(**over):
    """What Claude returns: nothing but the answer unless a test says otherwise."""
    return dict({'answer': 'Here you go.', 'list': 'none', 'draft_text': '', 'draft_channel': 'none', 'cannot': False,
                 'open_screen': 'none', 'notes_used': [], 'follow_ups': []}, **over)


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workSidekick(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'c2w_sk_agent', groups='chat2work.group_agent')
        cls.other = new_test_user(cls.env, 'c2w_sk_other', groups='chat2work.group_agent')
        cls.checker = new_test_user(cls.env, 'c2w_sk_checker', groups='chat2work_verify.group_id_check')
        cls.admin = new_test_user(cls.env, 'c2w_sk_admin', groups='base.group_system')
        cls.Ws = cls.env['chat2work.workspace'].with_user(cls.agent)
        cls.CheckerWs = cls.env['chat2work.workspace'].with_user(cls.checker)
        Candidate = cls.env['chat2work.candidate']
        cls.thandi = Candidate.create({'name': 'Thandiwe Mokoena', 'phone': '+27825550142', 'whatsapp_opt_in': True})
        cls.lerato = Candidate.create({'name': 'Lerato Khumalo', 'phone': '+27715550107'})
        cls.sipho = Candidate.create({'name': 'Sipho Ndlovu', 'phone': '+27735550111'})
        cls.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', 'test-key')

    def setUp(self):
        super().setUp()
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        patch('odoo.addons.chat2work_contact.wizards.chat2work_message._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)

    def _log(self, candidate, channel, direction, text, minutes_ago=0):
        candidate._c2w_ucx_log(channel, [{
            'dir': direction, 'text': text, 'at': fields.Datetime.now() - timedelta(minutes=minutes_ago)}])

    def _ask(self, question, answer, ws=None, chat_id=False, candidate=None):
        """(the chat as the screen gets it, what was sent to the AI)."""
        with patch(AI, side_effect=lambda env, key, system, content, schema: answer) as ai:
            # `ws or self.Ws` would be wrong: an abstract model's recordset is always empty, so falsy.
            chat = (self.Ws if ws is None else ws).ws_sidekick_ask(chat_id, question, candidate and candidate.id)
        return chat, ai.call_args.args[3] if ai.called else ''

    def _ids(self, ws, key):
        return [row['id'] for row in ws._sidekick_list(key, 50)['rows']]

    # ── Chats ────────────────────────────────────────────────────────────────

    def test_chats_are_private_to_their_agent(self):
        chat, _sent = self._ask('Who needs help right now?', said())
        self.assertEqual(chat['name'], 'Who needs help right now?')     # titled by the first question
        self.assertEqual([m['role'] for m in chat['messages']], ['agent', 'sidekick'])
        self.assertEqual([c['id'] for c in self.Ws.ws_sidekick_chats()], [chat['id']])

        OtherWs = self.env['chat2work.workspace'].with_user(self.other)
        self.assertFalse(OtherWs.ws_sidekick_chats())
        self.assertFalse(OtherWs.ws_sidekick_chat(chat['id']))
        refused, sent = self._ask('And callbacks?', said(), ws=OtherWs, chat_id=chat['id'])
        self.assertIn('error', refused)
        self.assertFalse(sent)
        for user in (self.other, self.admin):       # the record rule holds outside the workspace calls too
            self.assertFalse(self.env['chat2work.sidekick.chat'].with_user(user).search([]))
            self.assertFalse(self.env['chat2work.sidekick.message'].with_user(user).search([]))

        # A follow-up stays in the same chat, and the model is given the earlier turn.
        again, sent = self._ask('And callbacks?', said(answer='None open.'), chat_id=chat['id'])
        self.assertEqual(again['id'], chat['id'])
        self.assertEqual(len(again['messages']), 4)
        self.assertIn('Agent asked: Who needs help right now?', sent)
        self.assertEqual(self.Ws.ws_sidekick_chats()[0]['preview'], 'None open.')

    def test_candidate_chat_is_reused_and_titled_by_the_candidate(self):
        blank = self.Ws.ws_sidekick_for_candidate(self.thandi.id)
        self.assertEqual((blank['id'], blank['messages'], blank['candidate']['id']), (False, [], self.thandi.id))
        self.assertFalse(self.Ws.ws_sidekick_chats())                   # nothing is kept until a question is asked
        chat, sent = self._ask('What has been tried?', said(), candidate=self.thandi)
        self.assertEqual(chat['name'], 'Thandiwe Mokoena')
        self.assertIn('First name: Thandiwe', sent)
        self.assertIn("Thandiwe's timeline", chat['messages'][-1]['source'])
        self.assertEqual(self.Ws.ws_sidekick_for_candidate(self.thandi.id)['id'], chat['id'])
        self.assertEqual([c['id'] for c in self.Ws.ws_sidekick_chats('cand')], [chat['id']])

    def test_no_key_or_no_answer_keeps_nothing(self):
        with patch(AI, side_effect=ValueError('Anthropic returned 529')):
            result = self.Ws.ws_sidekick_ask(False, 'Who needs help?')
        self.assertIn('error', result)
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', '')
        self.assertFalse(self.Ws.ws_sidekick_start()['ai'])
        result, sent = self._ask('Who needs help?', said())
        self.assertIn('error', result)
        self.assertFalse(sent)
        self.assertFalse(self.env['chat2work.sidekick.chat'].sudo().search([('user_id', '=', self.agent.id)]))
        with self.assertRaises(AccessError):
            self.env['chat2work.workspace'].with_user(
                new_test_user(self.env, 'c2w_sk_outsider', groups='base.group_user')).ws_sidekick_start()

    # ── Lists ────────────────────────────────────────────────────────────────

    def test_each_named_list_returns_the_right_candidates(self):
        for key in ('needs_help', 'callbacks_open', 'callbacks_overdue', 'cv_started', 'jobs_ready'):
            self.assertFalse(self._ids(self.Ws, key), key)
        self.assertEqual(set(self._ids(self.Ws, 'no_cv')), {self.thandi.id, self.lerato.id, self.sipho.id})
        self.assertNotIn('Waiting today', [g['title'] for g in self.Ws.ws_sidekick_start()['suggestions']])

        # Needs help: the same candidates and reasons as the inbox filter, longest wait first.
        self._log(self.thandi, 'whatsapp', 'inbound', 'I am stuck, please help', minutes_ago=5)
        self._log(self.lerato, 'sms', 'inbound', 'Thanks', minutes_ago=60 * 30)
        help_list = self.Ws._sidekick_list('needs_help')
        self.assertEqual([row['id'] for row in help_list['rows']], [self.lerato.id, self.thandi.id])
        self.assertEqual(help_list['rows'][0]['reason'], 'Waiting more than a day for a reply')
        self.assertEqual(sorted(row['id'] for row in help_list['rows']), sorted(r['id'] for r in self.Ws.ws_inbox('help')))

        # Callbacks: open, and overdue once a day old.
        callback = self.env['chat2work.callback.request'].create(
            {'candidate_id': self.sipho.id, 'phone': self.sipho.phone, 'channel': 'ussd'})
        self.assertEqual(self._ids(self.Ws, 'callbacks_open'), [self.sipho.id])
        self.assertFalse(self._ids(self.Ws, 'callbacks_overdue'))
        self.env.cr.execute("UPDATE chat2work_callback_request SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(hours=30), callback.id])
        callback.invalidate_recordset()
        self.assertEqual(self._ids(self.Ws, 'callbacks_overdue'), [self.sipho.id])
        callback.state = 'done'
        self.assertFalse(self._ids(self.Ws, 'callbacks_open'))

        # CV started and no CV.
        self.thandi.sudo().cv_state = 'started'
        self.lerato.sudo().cv_state = 'built'
        self.assertEqual(self._ids(self.Ws, 'cv_started'), [self.thandi.id])
        self.assertEqual(self._ids(self.Ws, 'no_cv'), [self.sipho.id])

        # Job matches ready to send: approved, on an open listing, not yet sent.
        source = self.env['chat2work.listing.source'].create({'name': 'Test source'})
        listing = self.env['chat2work.listing'].create(
            {'title': 'Call Centre Agent', 'source_id': source.id, 'verification_state': 'verified'})
        match = self.env['chat2work.listing.match'].create({'listing_id': listing.id, 'candidate_id': self.lerato.id})
        self.assertFalse(self._ids(self.Ws, 'jobs_ready'))
        match.action_approve()
        self.assertEqual(self._ids(self.Ws, 'jobs_ready'), [self.lerato.id])
        self.assertEqual(self.Ws.ws_counts()['lists']['jobs_ready'], 1)
        self.assertEqual([r['id'] for r in self.Ws.ws_candidates('jobs_ready')], [self.lerato.id])

        waiting = [g for g in self.Ws.ws_sidekick_start()['suggestions'] if g['title'] == 'Waiting today'][0]['items']
        self.assertIn('Who needs help right now?', waiting)
        self.assertIn("Who started a CV but didn't finish?", waiting)
        self.assertNotIn('Which callbacks are overdue?', waiting)       # that list is empty again

    def test_answer_rows_come_from_the_servers_list(self):
        self._log(self.thandi, 'whatsapp', 'inbound', 'I am stuck, please help')
        chat, sent = self._ask('Who needs help right now?', said(
            answer='99 candidates need help: Bogus Person and Made Up.', list='needs_help',
            follow_ups=['Tell me about Thandiwe', 'Only CV help', 'a', 'b']))
        answer = chat['messages'][-1]
        self.assertEqual(answer['list']['total'], 1)
        self.assertEqual([(row['id'], row['name'], row['reason']) for row in answer['list']['rows']],
                         [(self.thandi.id, 'Thandiwe Mokoena', 'Their last message asks for help')])
        self.assertEqual(answer['list']['open'], {'view': 'inbox', 'pill': 'help', 'label': 'the inbox'})
        self.assertTrue(answer['source'].startswith('From the inbox at '))
        self.assertEqual(len(answer['follow_ups']), 3)
        self.assertIn('needs_help = candidates who need help: 1. First: Thandiwe (Their last message asks for help)', sent)
        # A list the model makes up, or one this agent may not see, shows nothing.
        for key in ('everyone', 'id_failed'):
            chat, _sent = self._ask('Which ID checks failed?', said(list=key))
            self.assertFalse(chat['messages'][-1]['list'])
        # Once the candidate is gone, so is their row: the chat keeps ids, not names.
        first = self.Ws.ws_sidekick_chats()[-1]['id']
        self.thandi.unlink()
        self.assertFalse(self.Ws.ws_sidekick_chat(first)['messages'][-1]['list']['rows'])

    # ── Drafts and refusals ──────────────────────────────────────────────────

    def test_draft_is_returned_and_nothing_is_sent_or_changed(self):
        self._log(self.thandi, 'whatsapp', 'inbound', 'Hello')
        Interaction = self.env['comm.interaction'].sudo()
        on_record = [('conversation_id.partner_id', '=', self.thandi.partner_id.id)]
        before = (Interaction.search_count(on_record), len(self.thandi.message_ids), self.thandi.stage,
                  self.thandi.write_date)
        with patch(WA, autospec=True) as send:
            chat, _sent = self._ask('Draft an SMS nudging her', said(
                answer='', draft_text='Hi Thandiwe,\nyour CV is almost done.', draft_channel='sms'), candidate=self.thandi)
            send.assert_not_called()
        self.assertEqual(chat['messages'][-1]['draft'], {'text': 'Hi Thandiwe, your CV is almost done.', 'channel': 'sms'})
        self.thandi.invalidate_recordset()
        self.assertEqual((Interaction.search_count(on_record), len(self.thandi.message_ids), self.thandi.stage,
                          self.thandi.write_date), before)
        # "Shorter" works on the draft it already wrote.
        _chat, sent = self._ask('Make that draft shorter', said(draft_text='Hi', draft_channel='sms'), chat_id=chat['id'])
        self.assertIn('Your draft (sms): Hi Thandiwe, your CV is almost done.', sent)

    def test_refusal_says_so_and_offers_the_screen(self):
        chat, _sent = self._ask('Just delete her', said(
            answer="I can't delete or change records.\nAn administrator can remove a candidate.", cannot=True),
            candidate=self.thandi)
        answer = chat['messages'][-1]
        self.assertEqual(answer['cannot'], "I can't delete or change records.")
        self.assertEqual(answer['text'], 'An administrator can remove a candidate.')
        self.assertEqual(answer['open'], {'candidate_id': self.thandi.id, 'label': 'Open candidate'})
        self.assertTrue(self.thandi.exists())
        chat, _sent = self._ask('Mark all callbacks done', said(answer="I can't change callbacks.", cannot=True,
                                                               open_screen='callbacks'))
        self.assertEqual(chat['messages'][-1]['open']['pill'], 'callbacks')
        self.assertFalse(chat['messages'][-1]['source'])

    # ── Notes and privacy ────────────────────────────────────────────────────

    def test_notes_are_passed_and_named_in_the_source(self):
        notes = self.env['chat2work.agent.note'].search([])
        self.assertTrue(notes, 'the starting notes are installed')
        self.env['chat2work.agent.note'].create({'name': 'Lunch', 'body': 'Lunch is at one.'})
        chat, sent = self._ask('When is lunch?', said(answer='1. At one.', notes_used=['Lunch', 'Made up']))
        self.assertIn('## Lunch\nLunch is at one.', sent)
        self.assertIn('## %s' % notes[0].name, sent)
        self.assertEqual(chat['messages'][-1]['source'], 'From the agent notes: "Lunch"')
        with self.assertRaises(AccessError):        # agents read the notes; administrators write them
            self.env['chat2work.agent.note'].with_user(self.agent).create({'name': 'x', 'body': 'y'})

    def test_no_phone_or_id_number_reaches_the_ai(self):
        self._log(self.thandi, 'whatsapp', 'inbound', 'Help, my ID is 9001015009087, call 082 555 0142')
        self.env['chat2work.callback.request'].create(
            {'candidate_id': self.lerato.id, 'phone': self.lerato.phone, 'channel': 'ussd'})
        sent = [self._ask('Who needs help? Her ID is 9001015009087 and number 0825550142', said(list='needs_help'))[1],
                self._ask('What did she say? 071 555 0107', said(), candidate=self.thandi)[1]]
        for content in sent:
            self.assertIn('Thandiwe', content)
            for secret in ('9001015009087', '0142', '0107', 'Mokoena', 'Khumalo', '+27'):
                self.assertNotIn(secret, content)
        stored = self.env['chat2work.sidekick.message'].sudo().search([('role', '=', 'agent')]).mapped('body')
        self.assertFalse([body for body in stored if '9001015009087' in body or '0142' in body])

    # ── ID checks ────────────────────────────────────────────────────────────

    def test_id_check_filters_and_card_honour_the_group(self):
        Candidate = self.env['chat2work.candidate'].sudo()
        self.thandi.sudo().write({'id_check_state': 'not_valid', 'id_check_at': fields.Datetime.now()})
        self.lerato.sudo().write({'id_check_state': 'failed', 'id_check_at': fields.Datetime.now()})
        self.sipho.sudo().write({'cv_state': 'built', 'id_number_hash': Candidate._id_number_hash(ID_NO),
                                 'id_number_encrypted': Candidate._id_number_encrypt(ID_NO)})

        # An agent who may not run checks: no counts, no list, no box, no sidekick list.
        self.assertFalse(self.Ws.ws_bootstrap()['can_id_check'])
        self.assertFalse([key for key in self.Ws.ws_counts()['lists'] if key.startswith('id_')])
        with self.assertRaises(AccessError):
            self.Ws.ws_candidates('idc', 'open')
        self.assertFalse(self.Ws.ws_candidate(self.thandi.id)['id_check'])
        self.assertFalse([key for key in self.Ws._sidekick_lists() if key.startswith('id_')])
        _chat, sent = self._ask('Which ID checks failed?', said())
        self.assertNotIn('id_failed', sent)
        self.assertNotIn('VerifyNow credits left', sent)

        # Staff who may: failed is "not valid", waiting is a check that didn't complete.
        lists = self.CheckerWs.ws_counts()['lists']
        self.assertEqual((lists['id_open'], lists['id_failed'], lists['id_waiting'], lists['id_not_done']), (2, 1, 1, 1))
        self.assertEqual({r['id'] for r in self.CheckerWs.ws_candidates('idc', 'open')}, {self.thandi.id, self.lerato.id})
        self.assertEqual([r['id'] for r in self.CheckerWs.ws_candidates('idc', 'failed')], [self.thandi.id])
        self.assertEqual([r['id'] for r in self.CheckerWs.ws_candidates('idc', 'waiting')], [self.lerato.id])
        row = self.CheckerWs.ws_candidates('idc', 'not_done')[0]
        self.assertEqual((row['id'], row['line']), (self.sipho.id, 'CV finished, no ID check yet'))
        self.assertEqual(self._ids(self.CheckerWs, 'id_failed'), [self.thandi.id])
        self.assertEqual(self._ids(self.CheckerWs, 'id_waiting'), [self.lerato.id])
        self.assertEqual(self._ids(self.CheckerWs, 'id_not_done'), [self.sipho.id])
        chat, sent = self._ask('Which ID checks failed?', said(list='id_failed'), ws=self.CheckerWs)
        self.assertIn('VerifyNow credits left', sent)
        self.assertEqual([row['id'] for row in chat['messages'][-1]['list']['rows']], [self.thandi.id])
        self.assertEqual(chat['messages'][-1]['list']['open']['sub'], 'failed')

        account = self.env['chat2work.verify.account']._get()
        account.write({'mode': 'production', 'available_credits': 42, 'balance_at': fields.Datetime.now()})
        card = self.CheckerWs.ws_candidate(self.sipho.id)['id_check']
        self.assertEqual((card['state'], card['can_run'], card['again'], card['cost']), ('none', True, False, 1))
        self.assertEqual((card['account']['credits'], card['account']['id']), (42, account.id))
        self.assertEqual(card['id_number'], '9111******086')
        # A result that was paid for is final; one that didn't complete can be run again.
        self.assertFalse(self.CheckerWs.ws_candidate(self.thandi.id)['id_check']['can_run'])
        self.assertEqual(self.CheckerWs.ws_candidate(self.thandi.id)['id_check']['tag'], ['bad', 'Failed'])
        self.assertFalse(self.CheckerWs.ws_candidate(self.lerato.id)['id_check']['can_run'])    # no ID number on record
        self.lerato.sudo().write({'id_number_hash': Candidate._id_number_hash('9001015009087'),
                                  'id_number_encrypted': Candidate._id_number_encrypt('9001015009087')})
        self.lerato.invalidate_recordset()
        waiting = self.CheckerWs.ws_candidate(self.lerato.id)['id_check']
        self.assertEqual((waiting['can_run'], waiting['tag']), (True, ['warn', 'Waiting']))
