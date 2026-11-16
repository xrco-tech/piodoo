# -*- coding: utf-8 -*-
"""The Employers section of the workspace."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workWorkspaceEmployers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'c2w_emp_agent', groups='chat2work.group_agent')
        cls.outsider = new_test_user(cls.env, 'c2w_emp_outsider', groups='base.group_user')
        cls.Ws = cls.env['chat2work.workspace'].with_user(cls.agent)
        cls.source = cls.env['chat2work.listing.source'].create({'name': 'Zze site'})
        Listing = cls.env['chat2work.listing']

        def job(employer, title, **vals):
            return Listing.create(dict({'title': title, 'source_id': cls.source.id, 'employer': employer}, **vals))

        cls.big = job('Zze Retail Group', 'Cashier', apply_url='https://www.zzeretail.example/jobs/1',
                      apply_contact='011 555 0142', location='Johannesburg').employer_id
        job('Zze Retail Group', 'Packer', apply_url='https://zzeretail.example/jobs/2', location='Pretoria')
        cls.small_job = job('Zze Mining', 'Driver')
        cls.small = cls.small_job.employer_id
        cls.twin = job('Zze Retail Grp', 'Clerk').employer_id

    def _ids(self, **kwargs):
        kwargs.setdefault('search', 'zze')
        return [row['id'] for row in self.Ws.ws_employers(**kwargs)]

    def test_agents_only(self):
        Outsider = self.env['chat2work.workspace'].with_user(self.outsider)
        for attempt in (Outsider.ws_employers, lambda: Outsider.ws_employer(self.big.id),
                        lambda: Outsider.ws_employer_save(self.big.id, {}, 'verified')):
            with self.assertRaises(AccessError):
                attempt()

    def test_list_and_count(self):
        # The employer with the most open jobs comes first.
        self.assertEqual(self._ids()[0], self.big.id)
        self.assertEqual(set(self._ids()), {self.big.id, self.small.id, self.twin.id})
        row = next(r for r in self.Ws.ws_employers(search='zze retail group'))
        self.assertEqual((row['jobs'], row['open'], row['state']), (2, 2, 'new'))
        before = self.Ws.ws_counts()['employers']
        self.Ws.ws_employer_save(self.small.id, {}, 'verified')
        self.assertEqual(self.Ws.ws_counts()['employers'], before - 1)
        self.assertNotIn(self.small.id, self._ids())
        self.assertEqual(self._ids(pill='verified'), [self.small.id])
        self.assertIn(self.small.id, self._ids(pill='all'))

    def test_detail_and_save(self):
        detail = self.Ws.ws_employer(self.big.id)
        self.assertEqual(detail['stats'][:2], [2, 2])
        self.assertEqual(detail['links'], [{'site': 'zzeretail.example', 'jobs': 2}])
        self.assertEqual(detail['contacts'], ['011 555 0142'])
        self.assertEqual(detail['places'], ['Johannesburg', 'Pretoria'])
        self.assertEqual([c['done'] for c in detail['checks']], [False] * 4)
        self.assertEqual([s['id'] for s in detail['similar']], [self.twin.id])

        saved = self.Ws.ws_employer_save(self.big.id, {
            'check_registered': True, 'check_confirmed': True, 'registration_no': ' 2014/123456/07 ',
            'note': 'Spoke to HR.', 'recruiter': True}, 'unsure')
        self.assertEqual(saved['state'], 'unsure')
        self.assertEqual([c['done'] for c in saved['checks']], [True, False, True, False])
        self.assertEqual((saved['registration_no'], saved['note'], saved['recruiter']),
                         ('2014/123456/07', 'Spoke to HR.', True))
        self.assertEqual(saved['checked_by'], self.agent.name)
        self.assertTrue(any('Spoke to HR.' in h['text'] for h in saved['history']))
        # Notes alone do not change the answer.
        self.assertEqual(self.Ws.ws_employer_save(self.big.id, {'note': 'Called again.'})['state'], 'unsure')

    def test_join_and_not_same(self):
        self.assertEqual(self.Ws.ws_employer_not_same(self.big.id, self.twin.id)['similar'], [])
        joined = self.Ws.ws_employer_join(self.big.id, self.twin.id)
        self.assertEqual(joined['stats'][0], 3)
        self.assertIn('Zze Retail Grp', joined['names'])
        self.assertFalse(self.Ws.ws_employer(self.twin.id))

    def test_job_carries_the_flag_but_is_not_blocked(self):
        check = self.Ws.ws_listing(self.small_job.id)['employer_check']
        self.assertEqual((check['id'], check['state']), (self.small.id, 'new'))
        self.small_job.with_user(self.agent).action_mark_verified()
        self.assertEqual(self.small_job.verification_state, 'verified')
        self.Ws.ws_employer_save(self.small.id, {}, 'invalid')
        check = self.Ws.ws_listing(self.small_job.id)['employer_check']
        self.assertEqual((check['state'], check['by']), ('invalid', self.agent.name))
        self.assertEqual(self.small_job.verification_state, 'verified', 'a flag, never a block')
