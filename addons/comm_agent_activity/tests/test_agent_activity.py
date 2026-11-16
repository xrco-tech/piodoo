# -*- coding: utf-8 -*-
"""The activity lines and the Team report built on them."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestAgentActivity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = new_test_user(cls.env, 'caa_lead', groups='base.group_user,comm_agent_activity.group_supervisor')
        cls.thandi = new_test_user(cls.env, 'caa_thandi', groups='base.group_user', name='Thandi Mokoena')
        cls.sipho = new_test_user(cls.env, 'caa_sipho', groups='base.group_user', name='Sipho Khumalo')
        cls.Log = cls.env['comm.agent.activity']
        cls.Report = cls.env['comm.agent.activity.report']
        cls.partner = cls.env['res.partner'].create({'name': 'Zze Retail'})
        # Whatever the database already holds is not this test's business.
        cls.Log.search([]).unlink()
        report = type(cls.Report)
        agents = cls.thandi | cls.sipho
        for name, value in (('_sources', lambda self: [('chat2work', 'Chat2Work')]),
                            ('_agents', lambda self, source: agents)):
            patcher = patch.object(report, name, value)
            patcher.start()
            cls.addClassCleanup(patcher.stop)

    def _line(self, user, action, minutes_ago=0, **vals):
        return self.Log.create(dict({
            'user_id': user.id, 'source': 'chat2work', 'action': action,
            'at': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def test_log_is_for_people(self):
        line = self.Log.with_user(self.thandi)._log('job_check', 'chat2work', self.partner, result='verified', wait=42)
        self.assertEqual((line.user_id, line.res_model, line.res_id, line.name), (self.thandi, 'res.partner', self.partner.id, 'Zze Retail'))
        self.assertEqual(line.wait_seconds, 42)
        self.assertFalse(line.seconds, "nothing before it to measure from")
        second = self.Log.with_user(self.thandi)._log('match', 'chat2work', self.partner)
        self.assertTrue(second.seconds, "time since their last action")
        self.assertFalse(self.Log._log('job_check', 'chat2work', self.partner), "the system is not an agent")
        self.assertFalse(self.Log.with_user(self.thandi).with_context(agent_activity_off=True)._log('match', 'chat2work'))

    def test_reversed_by_someone_else(self):
        first = self.Log.with_user(self.thandi)._log('job_check', 'chat2work', self.partner, result='verified')
        self.Log.with_user(self.thandi)._reverse('job_check', self.partner, 'invalid')
        self.assertFalse(first.reversed, "changing your own mind is not a reversal")
        self.Log.with_user(self.sipho)._reverse('job_check', self.partner, 'verified')
        self.assertFalse(first.reversed, "the same answer is not a reversal")
        self.Log.with_user(self.sipho)._reverse('job_check', self.partner, 'invalid')
        self.assertTrue(first.reversed)
        self.assertEqual(first.reversed_by_id, self.sipho)

    def test_active_time(self):
        now = fields.Datetime.now()
        moments = [now, now + timedelta(minutes=5), now + timedelta(minutes=15), now + timedelta(hours=2)]
        # 60 to start, 5 and 10 minutes of gaps, then a new stretch.
        self.assertEqual(self.Report._active_seconds(moments), 60 + 300 + 600 + 60)
        self.assertEqual(self.Report._active_seconds([]), 0)

    def test_team(self):
        self._line(self.thandi, 'employer_check', 30, has_note=True)
        self._line(self.thandi, 'job_check', 25, seconds=200, has_note=True)
        self._line(self.thandi, 'reply', 20, wait_seconds=240)
        for minute in range(6):
            self._line(self.sipho, 'job_check', 10 - minute, seconds=20, reversed=minute < 2)
        with self.assertRaises(AccessError):
            self.Report.with_user(self.thandi).team('chat2work', 'today')
        team = self.Report.with_user(self.lead).team('chat2work', 'today')
        rows = {row['name']: row for row in team['rows']}
        thandi, sipho = rows['Thandi Mokoena'], rows['Sipho Khumalo']
        self.assertEqual(thandi['score'], 5 + 2 + 1)
        self.assertEqual(sipho['score'], 6 * 2 - 2 * 10)
        self.assertEqual(team['rows'][0]['name'], 'Thandi Mokoena', "best score first")
        self.assertEqual((sipho['fast'], sipho['fast_flag'], sipho['reversed'], sipho['noted']), (6, True, 2, 0))
        self.assertEqual((thandi['fast_flag'], thandi['noted'], thandi['wait_median']), (False, 100, 240))
        self.assertEqual(thandi['active_seconds'], 60 + 300 + 300)
        self.assertEqual([col['key'] for col in team['columns']], ['job_check', 'match', 'employer_check', 'reply'])
        self.assertEqual(team['total']['counts']['job_check'], 7)
        tiles = team['tiles']
        self.assertEqual((tiles['agents'], tiles['active'], tiles['actions'], tiles['reversed'], tiles['reversed_top']), (2, 2, 9, 2, 2))
        self.assertNotIn('waits', thandi)
        self.assertTrue(any(hour['n'] for hour in team['hours']))

    def test_agent_sees_only_themselves(self):
        self._line(self.thandi, 'job_check', 5, name='Cashier', result_label='Verified')
        self._line(self.sipho, 'job_check', 4)
        self._line(self.sipho, 'job_check', 3)
        with self.assertRaises(AccessError):
            self.Report.with_user(self.thandi).agent(self.sipho.id, 'chat2work', 'today')
        mine = self.Report.with_user(self.thandi).agent(False, 'chat2work', 'today')
        self.assertTrue(mine['own'])
        self.assertFalse(mine['supervisor'])
        self.assertEqual(mine['me']['counts']['job_check'], 1)
        self.assertEqual(mine['team']['counts']['job_check'], 2, "the average of 1 and 2, rounded to even")
        self.assertEqual([(line['action'], line['name'], line['result']) for line in mine['log']],
                         [('Job checked', 'Cashier', 'Verified')])
        self.assertEqual(mine['today'], [{'label': 'Job checked', 'n': 1}])
        self.assertEqual(len(mine['days']), 1)
        other = self.Report.with_user(self.lead).agent(self.sipho.id, 'chat2work', 'today')
        self.assertEqual((other['own'], other['me']['counts']['job_check']), (False, 2))

    def test_points(self):
        with self.assertRaises(AccessError):
            self.Report.with_user(self.thandi).points_save({'job_check': 3})
        with self.assertRaises(UserError):
            self.Report.with_user(self.lead).points_save({'job_check': 'lots'})
        saved = self.Report.with_user(self.lead).points_save({'job_check': '3,5', 'nonsense': 9})
        self.assertEqual({row['action']: row['points'] for row in saved['rows']}['job_check'], 3.5)
        self._line(self.thandi, 'job_check')
        row = self.Report.with_user(self.lead).team('chat2work', 'today')['rows'][0]
        self.assertEqual(row['score'], 4, "3.5 rounds to 4")
        self.assertFalse(self.Report.with_user(self.thandi).points()['can_edit'])

    def test_periods(self):
        self._line(self.thandi, 'job_check', 60 * 24 * 40)
        for period in ('today', 'week', 'last_week', 'month', 'nonsense'):
            team = self.Report.with_user(self.lead).team('chat2work', period)
            self.assertTrue(team['label'])
            self.assertEqual(team['tiles']['actions'], 0, "40 days ago is in none of them")
