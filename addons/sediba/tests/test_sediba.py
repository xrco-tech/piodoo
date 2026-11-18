# -*- coding: utf-8 -*-
"""Topics, findings and the rule for what counts as verified."""
from datetime import date

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSediba(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # An automated writer: no email address, only the researcher group.
        cls.agent = new_test_user(cls.env, 'sediba_agent', groups='base.group_user,sediba.group_user',
                                  email=False)
        cls.agent.partner_id.email = False
        cls.outsider = new_test_user(cls.env, 'sediba_outsider', groups='base.group_user')
        cls.Topic = cls.env['sediba.topic'].with_user(cls.agent)
        cls.Finding = cls.env['sediba.finding'].with_user(cls.agent)
        cls.Run = cls.env['sediba.run'].with_user(cls.agent)
        cls.topic = cls.Topic.create({'name': 'SA Youth and Harambee'})

    def _source(self, kind, name='A source', opened=True):
        return (0, 0, {'name': name, 'kind': kind, 'opened': opened, 'says': 'Something'})

    def test_new_finding_is_a_lead(self):
        finding = self.Finding.create({'name': 'Free and zero-rated', 'topic_id': self.topic.id})
        self.assertEqual(finding.status, 'lead')
        self.assertFalse(finding.recheck_by)

    def test_verified_needs_a_date_and_proof(self):
        finding = self.Finding.create({'name': 'Claim', 'topic_id': self.topic.id})
        with self.assertRaises(ValidationError):
            finding.write({'status': 'verified', 'checked_on': date(2026, 11, 18)})
        finding.write({'source_ids': [self._source('primary')]})
        with self.assertRaises(ValidationError):
            finding.status = 'verified'  # still no date
        finding.write({'status': 'verified', 'checked_on': date(2026, 11, 18)})
        self.assertEqual(finding.recheck_by, date(2027, 2, 16))

    def test_what_counts_as_proof(self):
        def verified(sources):
            return self.Finding.create({
                'name': 'Claim', 'topic_id': self.topic.id, 'status': 'verified',
                'checked_on': date(2026, 11, 18), 'source_ids': sources})

        verified([self._source('official')])
        verified([self._source('news', 'News24'), self._source('news', 'Daily Maverick')])
        for weak in (
            [self._source('news', 'News24')],
            [self._source('news', 'News24'), self._source('news', 'news24 ')],
            [self._source('sponsored', 'Business Day'), self._source('social', 'Facebook')],
            [self._source('primary', opened=False)],
        ):
            with self.assertRaises(ValidationError):
                verified(weak)

    def test_proof_cannot_be_taken_away(self):
        finding = self.Finding.create({
            'name': 'Claim', 'topic_id': self.topic.id, 'status': 'verified',
            'checked_on': date(2026, 11, 18), 'source_ids': [self._source('primary')]})
        source = finding.source_ids
        with self.assertRaises(ValidationError):
            source.opened = False
        with self.assertRaises(ValidationError):
            source.kind = 'sponsored'
        with self.assertRaises(ValidationError):
            source.unlink()
        finding.status = 'lead'
        source.unlink()
        self.assertFalse(finding.source_ids)

    def test_agent_without_email_can_change_text(self):
        finding = self.Finding.create({'name': 'Claim', 'topic_id': self.topic.id, 'statement': 'First'})
        finding.write({'statement': 'Second', 'why_it_matters': 'Because', 'needs_review': True})
        self.assertEqual(finding.statement, 'Second')

    def test_topic_counts_and_due_date(self):
        self.Finding.create({'name': 'Lead one', 'topic_id': self.topic.id})
        self.Finding.create({'name': 'Lead two', 'topic_id': self.topic.id})
        self.Finding.create({
            'name': 'Proven', 'topic_id': self.topic.id, 'status': 'verified',
            'checked_on': date(2026, 11, 18), 'source_ids': [self._source('primary')]})
        self.topic.invalidate_recordset()
        self.assertEqual((self.topic.verified_count, self.topic.lead_count, self.topic.unconfirmed_count), (1, 2, 0))
        self.assertFalse(self.topic.due_date)
        self.Run.create({'topic_id': self.topic.id, 'run_date': date(2026, 11, 18)})
        self.assertEqual(self.topic.last_researched, date(2026, 11, 18))
        self.assertEqual(self.topic.due_date, date(2026, 11, 25))
        # An older run does not move the date back.
        self.Run.create({'topic_id': self.topic.id, 'run_date': date(2026, 11, 1)})
        self.assertEqual(self.topic.last_researched, date(2026, 11, 18))

    def test_reference_is_unique(self):
        self.Finding.create({'name': 'One', 'topic_id': self.topic.id, 'ref': 'sayouth-free'})
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                self.Finding.create({'name': 'Two', 'topic_id': self.topic.id, 'ref': 'sayouth-free'})

    def test_only_researchers_get_in(self):
        with self.assertRaises(AccessError):
            self.env['sediba.finding'].with_user(self.outsider).search([])
        with self.assertRaises(AccessError):
            self.Finding.create({'name': 'Mine', 'topic_id': self.topic.id}).unlink()


@tagged('post_install', '-at_install')
class TestSedibaWorkspace(TransactionCase):
    """What the workspace screen reads and the two things it changes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'sediba_reader', groups='base.group_user,sediba.group_user',
                                 name='Naledi Dube')
        cls.outsider = new_test_user(cls.env, 'sediba_ws_outsider', groups='base.group_user')
        cls.Ws = cls.env['sediba.workspace'].with_user(cls.user)
        env = cls.env(user=cls.user)
        # Whatever the database already holds is not this test's business.
        cls.env['sediba.source'].search([]).unlink()
        cls.env['sediba.finding'].with_context(active_test=False).search([]).unlink()
        cls.env['sediba.run'].search([]).unlink()
        cls.env['sediba.topic'].with_context(active_test=False).search([]).unlink()
        cls.first = env['sediba.topic'].create({'name': 'First', 'sequence': 1, 'summary': 'One.\n\nTwo.'})
        cls.second = env['sediba.topic'].create({'name': 'Second', 'sequence': 2, 'scope': 'Look here.'})
        cls.proven = env['sediba.finding'].create({
            'name': 'Proven', 'topic_id': cls.first.id, 'statement': 'A fact about reach.',
            'source_ids': [(0, 0, {'name': 'Own page', 'kind': 'primary', 'says': 'It says so', 'url': 'https://example.org'}),
                           (0, 0, {'name': 'Snippet', 'kind': 'news', 'opened': False})]})
        cls.proven.write({'status': 'verified', 'checked_on': date(2026, 11, 18)})
        cls.lead = env['sediba.finding'].create({
            'name': 'Only a lead', 'topic_id': cls.first.id, 'needs_review': True, 'review_note': 'Keep or drop.'})

    def test_next_topic_and_nav(self):
        nav = self.Ws.ws_nav()
        self.assertEqual([t['name'] for t in nav['topics']], ['First', 'Second'])
        self.assertEqual((nav['all'], nav['review'], nav['runs']), (2, 1, 0))
        # Nothing researched yet: the first by order is next.
        self.assertEqual([t['next'] for t in nav['topics']], [True, False])
        self.env['sediba.run'].with_user(self.user).create({'topic_id': self.first.id, 'run_date': date(2026, 11, 18)})
        self.assertEqual([t['next'] for t in self.Ws.ws_nav()['topics']], [False, True])
        self.env['sediba.run'].with_user(self.user).create({'topic_id': self.second.id, 'run_date': date(2026, 11, 19)})
        # Both researched: the one due soonest.
        self.assertEqual([t['next'] for t in self.Ws.ws_nav()['topics']], [True, False])

    def test_overview(self):
        self.env['sediba.run'].with_user(self.user).create({
            'topic_id': self.first.id, 'run_date': date(2026, 11, 18), 'summary': 'Looked.'})
        data = self.Ws.ws_overview()
        self.assertEqual(data['counts'], {'lead': 1, 'verified': 1, 'unconfirmed': 0, 'review': 1})
        self.assertEqual(data['last_run']['date'], '18 Nov 2026')
        self.assertEqual(data['next']['name'], 'Second')
        self.assertEqual([f['name'] for f in data['review']], ['Only a lead'])

    def test_topic_page(self):
        data = self.Ws.ws_topic(self.first.id)
        self.assertEqual((data['position'], data['of']), (1, 2))
        self.assertEqual(data['summary'], ['One.', 'Two.'])
        self.assertEqual([c['key'] for c in data['columns']], ['verified', 'lead', 'unconfirmed'])
        columns = {c['key']: [f['name'] for f in c['findings']] for c in data['columns']}
        self.assertEqual(columns, {'lead': ['Only a lead'], 'verified': ['Proven'], 'unconfirmed': []})
        searched = self.Ws.ws_topic(self.first.id, 'reach')
        self.assertEqual(sum(len(c['findings']) for c in searched['columns']), 1)
        self.assertFalse(self.Ws.ws_topic(0))

    def test_finding_page(self):
        data = self.Ws.ws_finding(self.proven.id)
        self.assertEqual(data['checked'], '18 Nov 2026')
        self.assertEqual(data['recheck'], '16 Feb 2027')
        self.assertEqual([(p['kind'], p['count']) for p in data['evidence']['parts']], [('primary', 1)])
        self.assertEqual(data['evidence']['unopened'], 1)
        self.assertEqual([s['name'] for s in data['source_rows']], ['Own page', 'Snippet'])
        self.assertFalse(self.Ws.ws_finding(0))

    def test_lists(self):
        self.assertEqual(self.Ws.ws_findings()['total'], 2)
        self.assertEqual([f['name'] for f in self.Ws.ws_findings('review')['rows']], ['Only a lead'])
        self.assertEqual([f['name'] for f in self.Ws.ws_findings('verified')['rows']], ['Proven'])
        self.assertEqual(self.Ws.ws_findings('all', 'reach')['total'], 1)
        self.assertEqual(self.Ws.ws_runs()['total'], 0)

    def test_status_and_review_changes(self):
        # A lead with no proof cannot be marked verified from the screen either.
        with self.assertRaises(ValidationError):
            self.Ws.ws_set_status(self.lead.id, 'verified')
        data = self.Ws.ws_set_status(self.lead.id, 'unconfirmed')
        self.assertEqual(data['status'], 'unconfirmed')
        self.assertEqual(data['checked_by'], 'Naledi Dube')
        self.assertTrue(data['checked'])
        self.assertFalse(self.Ws.ws_set_review(self.lead.id, False)['review'])
        self.assertEqual(self.Ws.ws_set_status(self.proven.id, 'lead')['status'], 'lead')
        self.assertFalse(self.Ws.ws_set_status(self.lead.id, 'nonsense'))

    def test_outsiders_are_kept_out(self):
        ws = self.env['sediba.workspace'].with_user(self.outsider)
        for call in (ws.ws_nav, ws.ws_overview, lambda: ws.ws_topic(self.first.id),
                     lambda: ws.ws_finding(self.proven.id), ws.ws_findings, ws.ws_runs,
                     lambda: ws.ws_set_review(self.lead.id, False)):
            with self.assertRaises(AccessError):
                call()
