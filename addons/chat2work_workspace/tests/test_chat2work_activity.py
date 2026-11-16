# -*- coding: utf-8 -*-
"""What Chat2Work agents do is noted for the Team report."""
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workActivity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thandi = new_test_user(cls.env, 'c2w_act_thandi', groups='chat2work.group_agent', name='Thandi Mokoena')
        cls.sipho = new_test_user(cls.env, 'c2w_act_sipho', groups='chat2work.group_agent', name='Sipho Khumalo')
        cls.lead = new_test_user(
            cls.env, 'c2w_act_lead', groups='chat2work.group_agent,comm_agent_activity.group_supervisor')
        cls.Log = cls.env['comm.agent.activity']
        cls.Log.search([]).unlink()
        cls.Ws = cls.env['chat2work.workspace']
        cls.Report = cls.env['comm.agent.activity.report']
        source = cls.env['chat2work.listing.source'].create({'name': 'Zzq site'})
        Listing = cls.env['chat2work.listing']
        cls.job = Listing.create({'title': 'Zzq Cashier', 'source_id': source.id, 'employer': 'Zzq Retail Group'})
        cls.twin_job = Listing.create({'title': 'Zzq Packer', 'source_id': source.id, 'employer': 'Zzq Retail Grp'})

    def _lines(self, action):
        return self.Log.search([('action', '=', action)], order='id')

    def test_job_checks(self):
        self.job.action_mark_verified()
        self.assertFalse(self._lines('job_check'), "the system is not an agent")
        self.job.action_mark_unverified()
        self.job.with_user(self.thandi).action_mark_verified()
        line = self._lines('job_check')
        self.assertEqual((line.user_id, line.source, line.name, line.result, line.result_label, line.has_note),
                         (self.thandi, 'chat2work', 'Zzq Cashier', 'verified', 'Verified', False))
        self.job.with_user(self.thandi).action_mark_verified()
        self.assertEqual(len(self._lines('job_check')), 1, "already verified: nothing was done")
        self.job.with_user(self.sipho).action_mark_invalid()
        first, second = self._lines('job_check')
        self.assertTrue(first.reversed)
        self.assertEqual((first.reversed_by_id, second.result), (self.sipho, 'invalid'))
        # Taking a check back is not a check, but it does undo the other agent's.
        self.job.with_user(self.thandi).action_mark_unverified()
        self.assertEqual(len(self._lines('job_check')), 2)
        self.assertTrue(second.reversed)

    def test_employers(self):
        employer, twin = self.job.employer_id, self.twin_job.employer_id
        Ws = self.Ws.with_user(self.thandi)
        Ws.ws_employer_save(employer.id, {'note': 'Spoke to HR'})
        self.assertFalse(self._lines('employer_check'), "saving the checklist is not an answer")
        Ws.ws_employer_save(employer.id, {'note': 'Spoke to HR'}, 'verified')
        line = self._lines('employer_check')
        self.assertEqual((line.user_id, line.res_id, line.result, line.has_note), (self.thandi, employer.id, 'verified', True))
        self.Ws.with_user(self.sipho).ws_employer_save(employer.id, {}, 'invalid')
        self.assertTrue(line.reversed)
        Ws.ws_employer_join(employer.id, twin.id)
        joined = self._lines('employer_join')
        self.assertEqual((joined.user_id, joined.res_id), (self.thandi, employer.id))
        self.assertIn('Zzq Retail Grp', joined.result_label)

    def test_report(self):
        self.job.with_user(self.thandi).action_mark_verified()
        self.Ws.with_user(self.thandi).ws_employer_save(self.job.employer_id.id, {}, 'verified')
        self.assertIn(('chat2work', 'Chat2Work'), self.Report._sources())
        team = self.Report.with_user(self.lead).team('chat2work', 'today')
        rows = {row['name']: row for row in team['rows']}
        self.assertEqual(rows['Thandi Mokoena']['score'], 2 + 5)
        self.assertEqual(rows['Sipho Khumalo']['actions'], 0, "agents who did nothing are listed too")
        backlog = {item['key']: item for item in team['backlog']}
        self.assertEqual(set(backlog), {'employers', 'jobs'})
        self.assertGreaterEqual(backlog['employers']['waiting'], 1, "the twin employer is still to check")
        self.assertEqual((backlog['employers']['done'], backlog['jobs']['done']), (1, 1))
        mine = self.Report.with_user(self.thandi).agent(False, 'chat2work', 'today')
        self.assertEqual(len(mine['log']), 2)
