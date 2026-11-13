# -*- coding: utf-8 -*-
"""The numbers on the Contact Centre dashboard, and the menu split.

The database a test runs on may already hold conversations and calls, so the
counts are checked as changes: what the dashboard says after this test's own
messages and calls, against what it said before."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_dash_agent', tz='Africa/Johannesburg',
                                  groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.manager = new_test_user(cls.env, 'ccw_dash_manager', tz='Africa/Johannesburg',
                                    groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.outsider = new_test_user(cls.env, 'ccw_dash_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        # Whatever is already waiting is not this test's business.
        cls.env['contact.centre.contact'].search([]).write({'state': 'resolved'})
        cls.nomsa = cls._contact('Zzq Nomsa', '27990000711')
        cls.jabu = cls._contact('Zzq Jabu', '27990000722')
        cls.count = 0

    @classmethod
    def _contact(cls, name, mobile):
        partner = cls.env['res.partner'].create({'name': name, 'mobile': mobile})
        return cls.env['contact.centre.contact'].create({'partner_id': partner.id})

    def _msg(self, contact, minutes_ago, out=False, channel='whatsapp', **vals):
        return self.env['contact.centre.message'].create(dict({
            'contact_id': contact.id, 'channel': channel, 'direction': 'outbound' if out else 'inbound',
            'body_text': 'x', 'status': 'sent' if out else 'delivered',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _wa(self, wa_id, minutes_ago, incoming=False):
        type(self).count += 1
        return self.env['whatsapp.message'].create({
            'message_id': 'wamid.ccwdash_%s' % self.count, 'wa_id': wa_id, 'is_incoming': incoming,
            'message_type': 'text', 'message_body': 'x',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)})

    def _call(self, minutes_ago, incoming=True, status='answered', duration=0, **vals):
        type(self).count += 1
        number = '27990000711'
        return self.env['whatsapp.call.log'].create(dict({
            'call_id': 'ccwdash_call_%s' % self.count, 'call_direction': 'incoming' if incoming else 'outgoing',
            'call_status': status, 'call_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago),
            'duration': duration, 'from_number': number if incoming else '27100000000',
            'to_number': '27100000000' if incoming else number, 'agent_user_id': self.agent.id}, **vals))

    def test_who_may_look(self):
        with self.assertRaises(AccessError):
            self.env['contact.centre.workspace'].with_user(self.outsider).ws_dashboard()
        data = self.Ws.ws_dashboard()
        self.assertEqual((data['period'], data['is_agent'], data['is_manager']), ('today', True, False))
        # Sidekick's held changes are a manager's to see.
        self.assertIs(data['todo']['held'], False)
        self.assertEqual(self.Ws.ws_dashboard('nonsense')['period'], 'today')
        boss = self.env['contact.centre.workspace'].with_user(self.manager).ws_dashboard('7d')
        self.assertEqual((boss['period'], boss['is_manager']), ('7d', True))
        if 'contact.centre.ai.chat' in self.env:
            self.assertEqual(boss['todo']['held'], 0)

    def test_needs_you_now_and_messages(self):
        before = self.Ws.ws_dashboard('30d')
        self.assertEqual((before['todo']['unread'], before['todo']['waiting_since']), (0, False))

        self._msg(self.nomsa, 50)                                   # waiting, the oldest
        self._msg(self.jabu, 20, channel='sms')                     # waiting
        self._msg(self.jabu, 30, out=True, channel='sms', status='failed', failure_reason='No credit')
        self._msg(self.nomsa, 60 * 24 * 3, out=True, channel='email')
        after = self.Ws.ws_dashboard('30d')
        self.assertEqual(after['todo']['unread'], 2)
        waited = fields.Datetime.now() - fields.Datetime.to_datetime(after['todo']['waiting_since'])
        self.assertAlmostEqual(waited.total_seconds(), 50 * 60, delta=5)

        gained = lambda key: after['messages'][key] - before['messages'][key]
        self.assertEqual((gained('total'), gained('inbound'), gained('outbound'), gained('failed')), (4, 2, 2, 1))
        self.assertIn({'channel': 'SMS', 'n': 1}, after['messages']['failed_by'])
        # Fourteen bars, the last one today; calls are not messages.
        days = after['messages']['days']
        self.assertEqual(len(days), 14)
        self._msg(self.nomsa, 1, channel='voice')
        again = self.Ws.ws_dashboard('30d')['messages']
        self.assertEqual(again['total'], after['messages']['total'])
        day = lambda data, index, channel: data['messages']['days'][index][channel]
        self.assertEqual(sum(day(after, -1, c) + day(after, -2, c) - day(before, -1, c) - day(before, -2, c)
                             for c in ('whatsapp', 'sms')), 3)       # the three from the last hour (today, or yesterday near midnight)
        self.assertEqual(sum(d['email'] for d in days) - sum(d['email'] for d in before['messages']['days']), 1)

        # Today only: the email from three days ago is not in it.
        today = self.Ws.ws_dashboard('today')
        self.assertLessEqual(today['messages']['total'], after['messages']['total'] - 1)
        self.assertEqual(after['conversations']['open'] - before['conversations']['open'], 0)
        self.assertGreaterEqual(after['conversations']['open'], 2)

    def test_reply_times(self):
        before = self.Ws.ws_dashboard('7d')['replies']
        # Nomsa waited 10 minutes for an agent: two messages, one wait.
        self._msg(self.nomsa, 60)
        self._msg(self.nomsa, 55)
        self._msg(self.nomsa, 50, out=True)
        # A reply that failed does not end a wait; the next one does (40 minutes).
        self._msg(self.nomsa, 45)
        self._msg(self.nomsa, 44, out=True, status='failed')
        self._msg(self.nomsa, 5, out=True)
        # Jabu was answered by the bot within a minute: the thread has no copy of that.
        incoming = self._wa('27990000722', 30, incoming=True)
        self._msg(self.jabu, 30, whatsapp_message_id=incoming.id, provider_message_id=incoming.message_id)
        self._wa('27990000722', 29)
        # And is still waiting on a later one.
        self._msg(self.jabu, 2)

        replies = self.Ws.ws_dashboard('7d')['replies']
        self.assertEqual(replies['waits'] - before['waits'], 3)
        if not before['waits']:
            # 1, 10 and 40 minutes: the middle one, two of three within 15 minutes, one of three by the bot.
            self.assertEqual((replies['median_seconds'], replies['quick'], replies['auto']), (600, 67, 33))

    def test_calls_and_outcomes(self):
        # Seven days, so the half hour these calls span never straddles the user's midnight.
        before = self.Ws.ws_dashboard('7d')
        outcome = self.env['comm.disposition'].search([], limit=1) or self.env['comm.disposition'].create({'name': 'Zzq Resolved'})
        self._call(30, duration=120, disposition_id=outcome.id)
        self._call(25, duration=240)
        self._call(20, status='ended')                               # nobody picked up
        self._call(15, incoming=False, status='answered', duration=60)
        after = self.Ws.ws_dashboard('7d')
        gained = lambda key: after['calls'][key] - before['calls'][key]
        self.assertEqual((gained('total'), gained('answered'), gained('missed'), gained('outgoing'), gained('talk_seconds')),
                         (4, 2, 1, 1, 420))
        self.assertTrue(after['calls']['average_seconds'])
        line = next(l for l in after['calls']['lines'] if l['line'] == 'whatsapp')
        self.assertGreaterEqual(line['total'], 4)
        self.assertIn(outcome.name, [o['name'] for o in after['outcomes']])
        # Two connected calls have no outcome yet: one in, one out. The missed one is not waiting for one.
        self.assertEqual(after['todo']['no_outcome'] - before['todo']['no_outcome'], 2)
        self.assertGreaterEqual(after['todo']['missed_today'], before['todo']['missed_today'])

    def test_campaigns_and_hours(self):
        Campaign = self.env['contact.centre.campaign']
        before = self.Ws.ws_dashboard()['campaigns']
        template = self.env['contact.centre.template'].create({'name': 'Zzq', 'channel': 'whatsapp', 'body_text': 'x'})
        running = Campaign.create({
            'name': 'Zzq Renewals', 'campaign_type': 'outbound', 'channel': 'whatsapp', 'template_id': template.id,
            'contact_ids': [(6, 0, (self.nomsa | self.jabu).ids)], 'state': 'running', 'send_progress': 1,
            'date_start': fields.Datetime.now()})
        Campaign.create({'name': 'Zzq Draft', 'campaign_type': 'inbound', 'channel': 'sms'})
        self._msg(self.nomsa, 10, out=True, campaign_id=running.id, status='failed')
        data = self.Ws.ws_dashboard()
        campaigns = data['campaigns']
        self.assertEqual((campaigns['running'] - before['running'], campaigns['draft'] - before['draft']), (1, 1))
        row = next(r for r in campaigns['rows'] if r['id'] == running.id)
        self.assertEqual((row['state'], row['outbound'], row['total'], row['done'], row['failed'], row['messages']),
                         ('running', True, 2, 1, 1, 1))
        self.assertLessEqual(len(campaigns['rows']), 4)
        # Fourteen hours, 06:00 to 19:00, in the user's own time.
        self.assertEqual([h['hour'] for h in data['hours']], list(range(6, 20)))

    def test_menus(self):
        """The app has Workspace, Dashboard and Configuration; the rest is under Configuration."""
        ref = self.env.ref
        root = ref('contact_centre.menu_contact_centre_main')
        config = ref('contact_centre.menu_contact_centre_config')
        # Every menu, not only the ones this test's user may see (Workspace is for agents).
        top = self.env['ir.ui.menu'].with_context(**{'ir.ui.menu.full_list': True}).search([('parent_id', '=', root.id)])
        expected = ref('contact_centre_workspace.menu_contact_centre_workspace') | ref('contact_centre.menu_contact_centre_overview') | config
        self.assertEqual(top, expected)
        self.assertEqual(top.sorted('sequence').mapped('name'), ['Workspace', 'Dashboard', 'Configuration'])
        for xmlid in ('contact_centre.menu_contact_centre_contacts', 'contact_centre.menu_contact_centre_messages',
                      'contact_centre.menu_contact_centre_campaigns', 'contact_centre.menu_contact_centre_chatbots',
                      'contact_centre_inbox.menu_contact_centre_inbox', 'contact_centre_ai_ops.menu_contact_centre_ai_ops'):
            menu = ref(xmlid, raise_if_not_found=False)
            if menu:                                                  # the copilot addon is optional
                self.assertEqual(menu.parent_id, config, xmlid)
        self.assertEqual(ref('contact_centre.menu_contact_centre_overview').action.tag, 'contact_centre_dashboard')
