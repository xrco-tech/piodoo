# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSoftphoneCard(TransactionCase):
    """Reads and actions behind the softphone card."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, login='card_agent', groups='base.group_user', name='Card Agent')
        cls.other = new_test_user(cls.env, login='card_other', groups='base.group_user', name='Other Agent')
        cls.agent.dialer_sip_ext = '1001'
        cls.other.dialer_sip_ext = '1002'
        cls.Session = cls.env['comm.dialer.agent.session']
        cls.other_session = cls.Session.create({'user_id': cls.other.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Thandiwe Mokoena', 'mobile': '+27825550142'})
        now = fields.Datetime.now()
        Call = cls.env['comm.voip.call']
        cls.answered = Call.create({
            'direction': 'outgoing', 'to_number': '+27825550142', 'from_number': '1001',
            'partner_id': cls.partner.id, 'agent_user_id': cls.agent.id, 'state': 'completed',
            'start_time': now - timedelta(minutes=10), 'duration': 252,
        })
        cls.missed = Call.create({
            'direction': 'incoming', 'from_number': '0715550107', 'to_number': '1001',
            'agent_user_id': cls.agent.id, 'state': 'no_answer', 'start_time': now - timedelta(days=1),
        })
        cls.not_mine = Call.create({
            'direction': 'outgoing', 'to_number': '0600000000', 'from_number': '1002',
            'agent_user_id': cls.other.id, 'state': 'completed', 'start_time': now,
        })

    def test_recent_lists_only_my_calls_newest_first(self):
        res = self.Session.with_user(self.agent).softphone_recent()
        self.assertEqual([c['id'] for c in res['calls']], [self.answered.id, self.missed.id])
        self.assertEqual(res['contacts'], [])
        first, second = res['calls']
        self.assertEqual(first['name'], 'Thandiwe Mokoena')
        self.assertEqual(first['number'], '+27825550142')
        self.assertTrue(first['answered'])
        self.assertEqual(first['duration'], 252)
        self.assertEqual(second['name'], '0715550107')
        self.assertFalse(second['answered'])
        self.assertEqual(second['direction'], 'incoming')

    def test_recent_search_finds_calls_and_contacts(self):
        res = self.Session.with_user(self.agent).softphone_recent('thandiwe')
        self.assertEqual([c['id'] for c in res['calls']], [self.answered.id])
        self.assertEqual([p['id'] for p in res['contacts']], [self.partner.id])
        self.assertEqual(res['contacts'][0]['number'], '+27825550142')
        by_number = self.Session.with_user(self.agent).softphone_recent('555 0107')
        self.assertEqual(by_number['calls'], [])
        by_digits = self.Session.with_user(self.agent).softphone_recent('5550107')
        self.assertEqual([c['id'] for c in by_digits['calls']], [self.missed.id])

    def test_activities_are_my_call_activities_with_a_number(self):
        call_type = self.env['mail.activity.type'].search([('category', '=', 'phonecall')], limit=1)
        if not call_type:
            call_type = self.env['mail.activity.type'].create({'name': 'Call', 'category': 'phonecall'})
        todo = self.env.ref('mail.mail_activity_data_todo')
        model_id = self.env['ir.model']._get_id('res.partner')
        base = {'res_model_id': model_id, 'res_id': self.partner.id, 'user_id': self.agent.id}
        late = self.env['mail.activity'].create(dict(
            base, activity_type_id=call_type.id, summary='CV follow-up',
            date_deadline=fields.Date.today() - timedelta(days=2)))
        self.env['mail.activity'].create(dict(base, activity_type_id=todo.id, summary='Not a call'))
        self.env['mail.activity'].create(dict(
            base, activity_type_id=call_type.id, user_id=self.other.id, summary='Someone else'))
        rows = self.Session.with_user(self.agent).softphone_activities()
        self.assertEqual([r['id'] for r in rows], [late.id])
        self.assertEqual(rows[0]['number'], '+27825550142')
        self.assertTrue(rows[0]['late'])
        self.assertEqual(rows[0]['summary'], 'CV follow-up')

    def test_transfer_targets_exclude_me_and_agents_without_a_phone(self):
        self.Session.create({'user_id': self.agent.id})
        nophone = new_test_user(self.env, login='card_nophone', groups='base.group_user')
        self.Session.create({'user_id': nophone.id})
        targets = self.Session.with_user(self.agent).softphone_transfer_targets()
        self.assertEqual([t['id'] for t in targets], [self.other_session.id])
        self.assertEqual(targets[0]['ext'], '1002')
        self.assertEqual(targets[0]['state_label'], 'Offline')

    def test_blind_transfer_needs_a_live_call(self):
        Session = self.Session.with_user(self.agent)
        res = Session.softphone_transfer(self.answered.id, self.other_session.id, 'blind')
        self.assertFalse(res['ok'])
        self.answered.state = 'in_progress'
        res = Session.softphone_transfer(self.answered.id, self.other_session.id, 'blind')
        self.assertTrue(res['ok'])
        transfer = self.env['comm.dialer.transfer'].browse(res['id'])
        self.assertEqual(transfer.mode, 'blind')
        self.assertEqual(transfer.target_endpoint, 'PJSIP/1002')
        self.assertEqual(transfer.requested_by, self.agent)

    def test_attended_transfer_can_be_handed_over_or_taken_back(self):
        Session = self.Session.with_user(self.agent)
        self.answered.state = 'in_progress'
        res = Session.softphone_transfer(self.answered.id, self.other_session.id, 'attended')
        self.assertEqual(res['mode'], 'attended')
        transfer = self.env['comm.dialer.transfer'].browse(res['id'])
        transfer.state = 'consulting'   # the phone service has connected the two agents
        self.assertTrue(Session.softphone_transfer_status(transfer.id)['live'])
        # Someone else can't decide it.
        self.Session.with_user(self.other).softphone_transfer_decide(transfer.id, True)
        self.assertEqual(transfer.state, 'consulting')
        self.assertEqual(Session.softphone_transfer_decide(transfer.id, True)['state'], 'completing')
        transfer.state = 'consulting'
        self.assertEqual(Session.softphone_transfer_decide(transfer.id, False)['state'], 'cancelling')
        transfer.state = 'done'
        self.assertFalse(Session.softphone_transfer_status(transfer.id)['live'])
