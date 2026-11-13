# -*- coding: utf-8 -*-
"""The numbers on the Chat2Work dashboard, who sent a message, and the menu split.

The database a test runs on may already hold candidates and messages, so the
counts are checked as changes against what the dashboard said before."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'c2w_dash_agent', groups='chat2work.group_agent', tz='Africa/Johannesburg')
        cls.outsider = new_test_user(cls.env, 'c2w_dash_outsider', groups='base.group_user')
        cls.Ws = cls.env['chat2work.workspace'].with_user(cls.agent)
        Candidate = cls.env['chat2work.candidate']
        cls.thandi = Candidate.create({'name': 'Zzq Thandiwe', 'phone': '+27990000811', 'whatsapp_opt_in': True,
                                       'registered_via': 'whatsapp'})
        cls.lerato = Candidate.create({'name': 'Zzq Lerato', 'phone': '+27990000822'})

    def setUp(self):
        super().setUp()
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        patch('odoo.addons.chat2work_contact.wizards.chat2work_message._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)

    def _log(self, candidate, direction, minutes_ago=0, channel='whatsapp', user=None, **entry):
        record = candidate.with_user(user) if user else candidate
        record._c2w_ucx_log(channel, [dict({
            'dir': direction, 'text': 'x', 'at': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **entry)])

    def test_agents_only(self):
        with self.assertRaises(AccessError):
            self.env['chat2work.workspace'].with_user(self.outsider).ws_dashboard()
        data = self.Ws.ws_dashboard()
        self.assertEqual(data['period'], 'today')
        self.assertEqual(self.Ws.ws_dashboard('nonsense')['period'], 'today')
        self.assertEqual(self.Ws.ws_dashboard('30d')['period'], '30d')
        # This agent may not run ID checks, so there is nothing about them.
        self.assertIs(data['ids'], False)
        self.assertIs(data['todo']['id_open'], False)

    def test_needs_you_now(self):
        before = self.Ws.ws_dashboard()['todo']
        self._log(self.thandi, 'outbound', 60)
        self._log(self.thandi, 'inbound', 50)                         # waiting, the oldest of ours
        self._log(self.lerato, 'inbound', 20, channel='sms')          # waiting
        self._log(self.lerato, 'inbound', 5, channel='ussd')          # a USSD session is not waiting for anyone
        self.env['chat2work.callback.request'].create({'candidate_id': self.lerato.id, 'phone': self.lerato.phone})
        todo = self.Ws.ws_dashboard()['todo']
        self.assertEqual(todo['reply'] - before['reply'], 2)
        self.assertEqual(todo['callbacks'] - before['callbacks'], 1)
        self.assertEqual(todo['callbacks_new'] - before['callbacks_new'], 1)
        self.assertTrue(todo['callback_since'])
        if not before['reply']:
            waited = fields.Datetime.now() - fields.Datetime.to_datetime(todo['reply_since'])
            self.assertAlmostEqual(waited.total_seconds(), 50 * 60, delta=5)
        # An answer takes them off.
        self._log(self.thandi, 'outbound', 1)
        self.assertEqual(self.Ws.ws_dashboard()['todo']['reply'] - before['reply'], 1)

    def test_who_sent_it(self):
        """A message an agent sends is marked as theirs; one Chat2Work sends by itself is automatic."""
        Interaction = self.env['comm.interaction']
        last = lambda: Interaction.search([], order='id desc', limit=1)
        self._log(self.thandi, 'outbound', 3, user=self.agent)
        self.assertEqual(last().c2w_sender, 'agent')
        self._log(self.thandi, 'outbound', 2)                         # no signed-in agent: the bot, a job, a webhook
        self.assertEqual(last().c2w_sender, 'auto')
        self._log(self.thandi, 'inbound', 1, user=self.agent)
        self.assertFalse(last().c2w_sender)

    def test_reply_times(self):
        before = self.Ws.ws_dashboard('7d')['replies']
        # Thandi waited 10 minutes for an agent: two messages, one wait.
        self._log(self.thandi, 'inbound', 60)
        self._log(self.thandi, 'inbound', 55)
        self._log(self.thandi, 'outbound', 50, user=self.agent)
        # A message that failed to send does not end a wait; the next one does (40 minutes).
        self._log(self.thandi, 'inbound', 45)
        self._log(self.thandi, 'outbound', 44, user=self.agent, status='failed')
        self._log(self.thandi, 'outbound', 5, user=self.agent)
        # Lerato was answered by Chat2Work itself within a minute, and is waiting on a later SMS.
        self._log(self.lerato, 'inbound', 30, channel='sms')
        self._log(self.lerato, 'outbound', 29, channel='sms')
        self._log(self.lerato, 'inbound', 2, channel='sms')
        # USSD is not a conversation an agent answers.
        self._log(self.lerato, 'inbound', 10, channel='ussd')

        replies = self.Ws.ws_dashboard('7d')['replies']
        self.assertEqual(replies['waits'] - before['waits'], 3)
        self.assertEqual(replies['inbound'] - before['inbound'], 5)
        self.assertEqual(replies['auto_known'] - before['auto_known'], 3)
        if not before['waits']:
            # 1, 10 and 40 minutes: the middle one, two of three within 15 minutes, one of three automatic.
            self.assertEqual((replies['median_seconds'], replies['quick'], replies['auto']), (600, 67, 33))

    def test_candidates_cvs_and_chart(self):
        before = self.Ws.ws_dashboard('7d')
        Candidate = self.env['chat2work.candidate']
        Candidate.create({'name': 'Zzq New on WhatsApp', 'phone': '+27990000833', 'registered_via': 'whatsapp'})
        Candidate.create({'name': 'Zzq New on USSD', 'phone': '+27990000844', 'registered_via': 'ussd'})
        Candidate.create({'name': 'Zzq New by import', 'phone': '+27990000855', 'registered_via': 'import'})
        self.thandi.sudo().write({'cv_state': 'built'})
        self.lerato.sudo().write({'cv_state': 'started', 'stage': 'help'})
        after = self.Ws.ws_dashboard('7d')

        self.assertEqual(after['new']['total'] - before['new']['total'], 3)
        self.assertEqual(after['new']['all'] - before['new']['all'], 3)
        days = after['new']['days']
        self.assertEqual(len(days), 14)
        gained = lambda key: sum(d[key] for d in days) - sum(d[key] for d in before['new']['days'])
        self.assertEqual((gained('whatsapp'), gained('ussd'), gained('other')), (1, 1, 1))

        cvs = lambda data, key: data['cvs'][key]
        self.assertEqual((cvs(after, 'done') - cvs(before, 'done'), cvs(after, 'started') - cvs(before, 'started')), (1, 1))
        self.assertEqual(cvs(after, 'none') - cvs(before, 'none'), 3 - 2)       # three new ones, two of ours moved on
        stage = lambda data, key: next(s['total'] for s in data['stages'] if s['id'] == key)
        self.assertEqual(stage(after, 'help') - stage(before, 'help'), 1)
        self.assertEqual([s['id'] for s in after['stages']][:2], ['new', 'help'])

    def test_jobs_and_bookings(self):
        data = self.Ws.ws_dashboard()
        self.assertLessEqual(len(data['jobs']['rows']), 4)
        self.assertLessEqual(len(data['bookings']['rows']), 4)
        before = data['bookings']['week']
        # A candidate gets their contact record with their first message; a booking is made against it.
        self._log(self.thandi, 'outbound', 1)
        self.assertTrue(self.thandi.partner_id)
        job = self.env['chat2work.job'].create({'name': 'Zzq Warehouse picker'})
        slot = self.env['chat2work.interview.slot'].create({
            'job_id': job.id, 'start_datetime': fields.Datetime.now() + timedelta(days=1), 'capacity': 2})
        self.env['chat2work.interview.booking'].create({
            'job_id': job.id, 'slot_id': slot.id, 'partner_id': self.thandi.partner_id.id, 'phone': self.thandi.phone})
        bookings = self.Ws.ws_dashboard()['bookings']
        self.assertEqual(bookings['week'] - before, 1)
        if not before:
            row = bookings['rows'][0]
            self.assertEqual((row['what'], row['candidate_id']), ('Zzq Warehouse picker', self.thandi.id))
            self.assertTrue(row['who'])

    def test_menus(self):
        """The app has Workspace, Dashboard and Configuration; every other screen is under Configuration."""
        ref = self.env.ref
        Menu = self.env['ir.ui.menu'].with_context(**{'ir.ui.menu.full_list': True})
        root = ref('chat2work.menu_chat2work_root')
        config = ref('chat2work.menu_chat2work_config')
        top = Menu.search([('parent_id', '=', root.id)]).sorted('sequence')
        self.assertEqual(top.mapped('name'), ['Workspace', 'Dashboard', 'Configuration'])
        self.assertEqual(ref('chat2work_workspace.menu_chat2work_dashboard').action.tag, 'chat2work_dashboard')
        for xmlid in ('chat2work.menu_chat2work_candidates', 'chat2work.menu_chat2work_bookings',
                      'chat2work.menu_chat2work_ussd_sessions', 'chat2work.menu_chat2work_ussd_simulator',
                      'chat2work_jobs.menu_chat2work_listings', 'chat2work_jobs.menu_chat2work_occupations',
                      'chat2work_verify.menu_chat2work_verify_root', 'chat2work_workspace.menu_chat2work_agent_notes',
                      'chat2work_cv_templates.menu_chat2work_cv_templates'):
            menu = ref(xmlid, raise_if_not_found=False)
            if menu:                                                  # CV designs is its own, optional addon
                self.assertEqual(menu.parent_id, config, xmlid)
