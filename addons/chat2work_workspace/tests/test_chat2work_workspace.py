# -*- coding: utf-8 -*-
"""The workspace's read calls return what the screen shows, and only to agents."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workWorkspace(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'c2w_ws_agent', groups='chat2work.group_agent')
        cls.outsider = new_test_user(cls.env, 'c2w_ws_outsider', groups='base.group_user')
        cls.Ws = cls.env['chat2work.workspace'].with_user(cls.agent)
        Candidate = cls.env['chat2work.candidate']
        cls.thandi = Candidate.create({'name': 'Thandiwe Mokoena', 'phone': '+27825550142', 'whatsapp_opt_in': True})
        cls.lerato = Candidate.create({'name': 'Lerato Khumalo', 'phone': '+27715550107'})

    def setUp(self):
        super().setUp()
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        patch('odoo.addons.chat2work_contact.wizards.chat2work_message._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)

    def _log(self, candidate, channel, direction, text, minutes_ago=0):
        candidate._c2w_ucx_log(channel, [{
            'dir': direction, 'text': text, 'at': fields.Datetime.now() - timedelta(minutes=minutes_ago)}])

    def test_agents_only(self):
        with self.assertRaises(AccessError):
            self.env['chat2work.workspace'].with_user(self.outsider).ws_bootstrap()
        boot = self.Ws.ws_bootstrap()
        self.assertEqual(boot['stages'][0], ['new', 'New'])
        self.assertFalse(boot['can_id_check'])
        with self.assertRaises(AccessError):
            self.Ws.ws_checks()

    def test_inbox_needs_reply_and_timeline(self):
        self._log(self.thandi, 'whatsapp', 'outbound', 'Welcome', minutes_ago=10)
        self._log(self.thandi, 'whatsapp', 'inbound', 'Please call me', minutes_ago=5)
        self._log(self.lerato, 'ussd', 'inbound', 'USSD session: 1 Register\nResult: registered')

        rows = {r['id']: r for r in self.Ws.ws_inbox()}
        self.assertTrue(rows[self.thandi.id]['needs_reply'])
        self.assertEqual(rows[self.thandi.id]['preview'], 'Please call me')
        # A USSD session is not something an agent replies to.
        self.assertFalse(rows[self.lerato.id]['needs_reply'])
        self.assertEqual(rows[self.lerato.id]['channel'], 'ussd')

        self.assertEqual([r['id'] for r in self.Ws.ws_inbox('reply')], [self.thandi.id])
        self.assertEqual(self.Ws.ws_counts()['inbox'], 1)
        self.assertEqual([r['id'] for r in self.Ws.ws_inbox('all', 'lerato')], [self.lerato.id])

        detail = self.Ws.ws_candidate(self.thandi.id)
        self.assertEqual([m['body'] for m in detail['timeline']], ['Welcome', 'Please call me'])
        self.assertFalse(detail['callback'])

        self._log(self.thandi, 'whatsapp', 'outbound', 'Calling you now')
        self.assertFalse(self.Ws.ws_inbox('reply'))

    def test_ussd_session_comes_with_its_screens(self):
        self._log(self.lerato, 'ussd', 'inbound', 'USSD session: an older one\nResult: done', minutes_ago=5)
        self.lerato._c2w_log_session('ussd', [
            {'at': '2026-11-10 10:00:00', 'dir': 'outbound', 'text': 'Hi Lerato. What would you like to do?\n1. Update Status\n0. Exit'},
            {'at': '2026-11-10 10:00:20', 'dir': 'inbound', 'text': 'Exit', 'key': '0'},
            {'at': '2026-11-10 10:00:21', 'dir': 'outbound', 'text': 'Session ended. Dial *134# to start again.'},
        ])
        new, old = self.Ws.ws_candidate(self.lerato.id)['timeline']    # by time: the session is dated earlier
        self.assertFalse(old['session'])
        self.assertEqual(new['body'], 'USSD session: Exit\nResult: Session ended. Dial *134# to start again.')
        self.assertEqual(new['session'][0]['picked'], '0')
        self.assertEqual([t['dir'] for t in new['session']], ['out', 'in', 'out'])
        # First and last times are what the screen works the session's length out from.
        self.assertEqual((new['session'][0]['at'], new['session'][-1]['at']), ('2026-11-10 10:00:00', '2026-11-10 10:00:21'))

    def test_changes_tell_open_workspaces_to_reload(self):
        def notices(sendone):
            return [c.args[1:] for c in sendone.call_args_list if c.args[0] == 'chat2work_workspace']

        with patch('odoo.addons.bus.models.bus.ImBus._sendone') as sendone:
            self._log(self.thandi, 'whatsapp', 'inbound', 'Hello')
            self.assertEqual(notices(sendone), [('chat2work_workspace/changed', {'what': 'timeline'})])
            self.env['chat2work.callback.request'].request_callback(phone='+27715550107', channel='ussd')
            self.assertIn(('chat2work_workspace/changed', {'what': 'callback'}), notices(sendone))
            # Someone who isn't a candidate: not the workspace's business.
            before = len(notices(sendone))
            stranger = self.env['res.partner'].create({'name': 'Not a candidate'})
            channel = self.env['comm.channel'].search([('code', '=', 'sms')], limit=1)
            conversation = self.env['comm.conversation'].create({'partner_id': stranger.id, 'primary_channel_id': channel.id})
            self.env['comm.interaction'].create({'conversation_id': conversation.id, 'channel_id': channel.id,
                                                 'direction': 'inbound', 'raw_body': 'Hi'})
            self.assertEqual(len(notices(sendone)), before)

    def test_cv_help_opens_the_candidates_own_page(self):
        with self.assertRaises(AccessError):
            self.env['chat2work.workspace'].with_user(self.outsider).ws_cv_help(self.lerato.id)
        self.assertFalse(self.lerato.sudo().cv_token)
        result = self.Ws.ws_cv_help(self.lerato.id)
        token = self.lerato.sudo().cv_token
        self.assertEqual(result['url'], '/cv/%s' % token)
        self.assertEqual(self.env['chat2work.candidate']._c2w_find_by_token(token), self.lerato)
        self.assertIn('opened the CV page', self.lerato.message_ids[0].body)
        # A link that is still valid is reused, so the one the candidate was sent keeps working.
        self.assertEqual(self.Ws.ws_cv_help(self.lerato.id)['url'], result['url'])

    def test_callbacks(self):
        self.env['chat2work.callback.request'].create(
            {'candidate_id': self.thandi.id, 'phone': self.thandi.phone, 'channel': 'whatsapp'})
        self.assertEqual([r['id'] for r in self.Ws.ws_inbox('callbacks')], [self.thandi.id])
        self.assertEqual(self.Ws.ws_counts()['callbacks'], 1)
        detail = self.Ws.ws_candidate(self.thandi.id)
        self.assertEqual(detail['callback']['state'], 'new')
        self.assertEqual(detail['stage'], 'help')
        stages = {s['id']: s for s in self.Ws.ws_pipeline()}
        self.assertEqual(stages['help']['callbacks'], 1)
        stage = self.Ws.ws_stage('help', 'callback')
        self.assertEqual([r['id'] for r in stage['rows']], [self.thandi.id])
        self.assertEqual(stage['total'], 1)

    def test_send_sms_and_closed_whatsapp_window(self):
        detail = self.Ws.ws_send(self.lerato.id, 'Hello Lerato')
        self.assertEqual(detail['timeline'][-1]['body'], 'Hello Lerato')
        self.assertEqual(detail['timeline'][-1]['channel'], 'sms')
        # Thandiwe uses WhatsApp but hasn't written in the last 24 hours.
        self.assertFalse(self.Ws.ws_candidate(self.thandi.id)['window_open'])
        with patch(WA, autospec=True) as send, self.assertRaises(UserError):
            self.Ws.ws_send(self.thandi.id, 'Hello Thandiwe')
        send.assert_not_called()
        # SMS has no such rule, so the agent can pick it instead.
        detail = self.Ws.ws_send(self.thandi.id, 'Hello Thandiwe', 'sms')
        self.assertEqual((detail['timeline'][-1]['body'], detail['timeline'][-1]['channel']), ('Hello Thandiwe', 'sms'))
        action = self.thandi.with_user(self.agent).with_context(default_channel='sms').action_c2w_open_message()
        self.assertEqual(action['context'], {'default_candidate_id': self.thandi.id, 'default_channel': 'sms'})

    def test_listings_and_slots(self):
        source = self.env['chat2work.listing.source'].create({'name': 'Test source'})
        listing = self.env['chat2work.listing'].create({'title': 'Call Centre Agent', 'source_id': source.id})
        self.assertEqual([r['id'] for r in self.Ws.ws_listings('to_verify')], [listing.id])
        self.assertEqual(self.Ws.ws_listing(listing.id)['verification_state'], 'unverified')

        # Paging: the next page starts where the last one ended, with no repeats.
        self.env['chat2work.listing'].create(
            [{'title': 'Listing %s' % n, 'source_id': source.id} for n in range(4)])
        first = self.Ws.ws_listings('to_verify', '', 0, 3)
        rest = self.Ws.ws_listings('to_verify', '', 3, 3)
        self.assertEqual((len(first), len(rest)), (3, 2))
        self.assertFalse({r['id'] for r in first} & {r['id'] for r in rest})
        self.assertEqual(len(self.Ws.ws_listings('to_verify', '', 0, 5)), 5)

        job = self.env['chat2work.job'].create({'name': 'Admin Clerk', 'location': 'Bellville'})
        slot = self.env['chat2work.interview.slot'].create(
            {'job_id': job.id, 'start_datetime': fields.Datetime.now() + timedelta(days=2), 'capacity': 2})
        partner = self.thandi._c2w_ucx_partner()
        self.env['chat2work.interview.booking'].create(
            {'slot_id': slot.id, 'job_id': job.id, 'partner_id': partner.id, 'phone': self.thandi.phone})
        self.assertIn(slot.id, [r['id'] for r in self.Ws.ws_slots()])
        detail = self.Ws.ws_slot(slot.id)
        self.assertEqual((detail['booked'], detail['open']), (1, 1))
        self.assertEqual(detail['bookings'][0]['candidate_id'], self.thandi.id)
