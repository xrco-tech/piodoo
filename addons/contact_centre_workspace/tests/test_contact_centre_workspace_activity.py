# -*- coding: utf-8 -*-
"""What Contact Centre agents do is noted for the Team report."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestContactCentreWorkspaceActivity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'cca_agent', groups='base.group_user,contact_centre.group_contact_centre_agent',
                                  name='Lindi Dube')
        cls.manager = new_test_user(cls.env, 'cca_manager', groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.Log = cls.env['comm.agent.activity']
        cls.Log.search([]).unlink()
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.Report = cls.env['comm.agent.activity.report']
        partner = cls.env['res.partner'].create({'name': 'Nokuthula Mabena', 'mobile': '27990000142'})
        cls.contact = cls.env['contact.centre.contact'].create({'partner_id': partner.id})

    def _msg(self, body, out=False, minutes_ago=0):
        return self.env['contact.centre.message'].create({
            'contact_id': self.contact.id, 'channel': 'whatsapp', 'direction': 'outbound' if out else 'inbound',
            'body_text': body, 'status': 'sent' if out else 'delivered',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)})

    def test_waiting(self):
        self.assertIsNone(self.contact._activity_waiting(), "nothing from them yet")
        self._msg('Hello', minutes_ago=30)
        self._msg('We will call you', out=True, minutes_ago=20)
        self.assertIsNone(self.contact._activity_waiting(), "already answered")
        self._msg('Thanks, when?', minutes_ago=10)
        self._msg('Hello?', minutes_ago=4)
        self.assertAlmostEqual(self.contact._activity_waiting(), 600, delta=5, msg="from the oldest one still waiting")

    def test_sent_and_closed(self):
        self._msg('Hello', minutes_ago=10)
        self.contact.with_user(self.agent)._activity_sent(self.contact._activity_waiting(), 'WhatsApp')
        reply = self.Log.search([('action', '=', 'reply')])
        self.assertEqual((reply.user_id, reply.source, reply.res_id), (self.agent, 'contact_centre', self.contact.id))
        self.assertAlmostEqual(reply.wait_seconds, 600, delta=5)
        self.contact.with_user(self.agent)._activity_sent(None, 'SMS')
        self.assertEqual(self.Log.search_count([('action', '=', 'outreach')]), 1, "nobody was waiting")

        self.Ws.ws_set_state(self.contact.id, 'pending')
        self.assertFalse(self.Log.search([('action', '=', 'close')]))
        self.Ws.ws_set_state(self.contact.id, 'resolved')
        self.Ws.ws_set_state(self.contact.id, 'resolved')
        self.assertEqual(self.Log.search_count([('action', '=', 'close')]), 1, "resolved twice is closed once")

    def test_report(self):
        self.Ws.ws_set_state(self.contact.id, 'resolved')
        self.assertIn(('contact_centre', 'Contact Centre'), self.Report._sources())
        with self.assertRaises(AccessError):
            self.Report.with_user(self.agent).team('contact_centre', 'today')
        team = self.Report.with_user(self.manager).team('contact_centre', 'today')
        self.assertEqual([col['key'] for col in team['columns']], ['reply', 'close', 'queue_call'])
        row = next(row for row in team['rows'] if row['name'] == 'Lindi Dube')
        self.assertEqual((row['counts'], row['score']), ({'close': 1}, 1))
        self.assertEqual([item['key'] for item in team['backlog']], ['queue'])
        mine = self.Report.with_user(self.agent).agent(False, 'contact_centre', 'today')
        self.assertEqual(mine['me']['counts'], {'close': 1})
