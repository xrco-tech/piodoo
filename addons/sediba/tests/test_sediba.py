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

    def test_assistant_switch_on_a_topic(self):
        # Off until someone allows it; the switch is the topic's, not a finding's.
        self.assertFalse(self.Ws.ws_topic(self.first.id)['ai_allowed'])
        self.assertTrue(self.Ws.ws_set_topic_ai(self.first.id, True)['ai_allowed'])
        self.assertTrue(self.first.ai_allowed)
        self.assertFalse(self.second.ai_allowed)
        self.assertFalse(self.Ws.ws_set_topic_ai(self.first.id, False)['ai_allowed'])
        # The public chatbot's switch is a second one and moves on its own.
        data = self.Ws.ws_set_topic_ai(self.first.id, True, False, True)
        self.assertEqual((data['public_allowed'], data['ai_allowed']), (True, False))
        self.assertFalse(self.Ws.ws_set_topic_ai(self.first.id, False, public=True)['public_allowed'])
        self.assertFalse(self.Ws.ws_set_topic_ai(0, True))
        with self.assertRaises(AccessError):
            self.env['sediba.workspace'].with_user(self.outsider).ws_set_topic_ai(self.first.id, True)

    def test_shown_in_on_a_topic(self):
        Space = self.env['sediba.space']
        app = Space.search([('code', '=', 'test_shown')]) or Space.create({'name': 'Shown app', 'code': 'test_shown'})
        self.first.space_ids = False
        data = self.Ws.ws_topic(self.first.id)
        self.assertEqual(data['space_ids'], [])
        self.assertIn([app.id, 'Shown app'], data['spaces'])
        data = self.Ws.ws_set_topic_spaces(self.first.id, [app.id, 999999])
        self.assertEqual((data['space_ids'], self.first.space_ids), ([app.id], app))
        self.assertEqual(self.Ws.ws_set_topic_spaces(self.first.id, [])['space_ids'], [])
        self.assertFalse(self.Ws.ws_set_topic_spaces(0, [app.id]))
        with self.assertRaises(AccessError):
            self.Ws.ws_set_topic_spaces(self.first.id, [app.id], 'test_shown')
        with self.assertRaises(AccessError):
            self.env['sediba.workspace'].with_user(self.outsider).ws_set_topic_spaces(self.first.id, [app.id])

    def test_outsiders_are_kept_out(self):
        ws = self.env['sediba.workspace'].with_user(self.outsider)
        for call in (ws.ws_nav, ws.ws_overview, lambda: ws.ws_topic(self.first.id),
                     lambda: ws.ws_finding(self.proven.id), ws.ws_findings, ws.ws_runs,
                     lambda: ws.ws_set_review(self.lead.id, False)):
            with self.assertRaises(AccessError):
                call()


@tagged('post_install', '-at_install')
class TestSedibaReference(TransactionCase):
    """The screen opened from inside another app as its Reference: only the
    verified findings on that app's topics, and nothing can be changed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = new_test_user(cls.env, 'sediba_app_reader', groups='base.group_user,sediba.group_reader')
        cls.researcher = new_test_user(cls.env, 'sediba_app_researcher', groups='base.group_user,sediba.group_user')
        cls.env['sediba.source'].search([]).unlink()
        cls.env['sediba.finding'].with_context(active_test=False).search([]).unlink()
        cls.env['sediba.run'].search([]).unlink()
        cls.env['sediba.topic'].with_context(active_test=False).search([]).unlink()
        Space = cls.env['sediba.space']
        cls.jobs = Space.search([('code', '=', 'test_jobs')]) or Space.create({'name': 'Jobs app', 'code': 'test_jobs'})
        cls.calls = Space.search([('code', '=', 'test_calls')]) or Space.create({'name': 'Calls app', 'code': 'test_calls'})
        Topic = cls.env['sediba.topic']
        cls.jobs_topic = Topic.create({'name': 'Job seekers', 'sequence': 1, 'space_ids': [(6, 0, cls.jobs.ids)],
                                       'summary': 'Known.', 'our_read': 'We think.'})
        cls.both_topic = Topic.create({'name': 'Regulation', 'sequence': 2, 'space_ids': [(6, 0, (cls.jobs | cls.calls).ids)]})
        cls.leads_topic = Topic.create({'name': 'Only leads', 'sequence': 3, 'space_ids': [(6, 0, cls.jobs.ids)]})
        cls.plain_topic = Topic.create({'name': 'Unmarked', 'sequence': 4})

        def finding(name, topic, verified=False, **vals):
            f = cls.env['sediba.finding'].create(dict(vals, name=name, topic_id=topic.id, source_ids=[
                (0, 0, {'name': 'Own page', 'kind': 'primary', 'says': 'It says so'})]))
            if verified:
                f.write({'status': 'verified', 'checked_on': date(2026, 11, 18)})
            return f

        cls.jobs_proven = finding('Jobs fact', cls.jobs_topic, True, needs_review=True, review_note='Pick one.',
                                  origin='Pasted notes', used_in='A page')
        cls.jobs_lead = finding('Jobs rumour', cls.jobs_topic)
        cls.both_proven = finding('Rule fact', cls.both_topic, True)
        cls.leads_lead = finding('A rumour', cls.leads_topic)
        cls.plain_proven = finding('Unmarked fact', cls.plain_topic, True)
        cls.env['sediba.run'].create({'topic_id': cls.jobs_topic.id, 'run_date': date(2026, 11, 18)})
        cls.Ws = cls.env['sediba.workspace'].with_user(cls.reader)

    def test_sediba_itself_still_shows_everything(self):
        nav = self.Ws.ws_nav()
        self.assertEqual((len(nav['topics']), nav['all'], nav['review'], nav['runs'], nav['reference']), (4, 5, 1, 1, False))

    def test_an_app_shows_only_its_verified_findings(self):
        jobs = self.Ws.ws_nav('test_jobs')
        # 'Only leads' is marked for the app but has nothing verified: it stays out.
        self.assertEqual([t['name'] for t in jobs['topics']], ['Job seekers', 'Regulation'])
        self.assertEqual((jobs['all'], jobs['review'], jobs['runs'], jobs['space'], jobs['reference']),
                         (2, 0, 0, 'Jobs app', True))
        self.assertEqual([t['name'] for t in self.Ws.ws_nav('test_calls')['topics']], ['Regulation'])
        self.assertEqual(self.Ws.ws_nav('no_such_app')['topics'], [])
        rows = self.Ws.ws_findings('all', '', 0, 40, 'test_jobs')['rows']
        self.assertEqual(sorted(f['name'] for f in rows), ['Jobs fact', 'Rule fact'])
        # Asking for leads from inside an app still gives verified only.
        self.assertEqual(self.Ws.ws_findings('lead', '', 0, 40, 'test_jobs')['total'], 2)
        self.assertEqual(self.Ws.ws_findings('all', 'rumour', 0, 40, 'test_jobs')['total'], 0)
        self.assertEqual(self.Ws.ws_runs(0, 40, 'test_jobs'), {'total': 0, 'rows': []})

    def test_overview_and_topic_in_an_app(self):
        overview = self.Ws.ws_overview('test_jobs')
        self.assertEqual(overview['counts'], {'verified': 2, 'lead': 0, 'unconfirmed': 0, 'review': 0})
        self.assertFalse(overview['last_run'] or overview['next'] or overview['review'])
        self.assertEqual([(t['name'], t['next']) for t in overview['topics']], [('Job seekers', False), ('Regulation', False)])
        topic = self.Ws.ws_topic(self.jobs_topic.id, '', 'test_jobs')
        self.assertEqual([c['key'] for c in topic['columns']], ['verified'])
        self.assertEqual([f['name'] for f in topic['columns'][0]['findings']], ['Jobs fact'])
        self.assertFalse(topic['columns'][0]['findings'][0]['review'])
        self.assertEqual((topic['summary'], topic['our_read'], topic['runs'], topic['due']), (['Known.'], '', [], False))
        self.assertFalse(self.Ws.ws_topic(self.jobs_topic.id, '', 'test_calls'))
        self.assertFalse(self.Ws.ws_topic(self.leads_topic.id, '', 'test_jobs'))
        self.assertEqual(self.Ws.ws_topic(self.both_topic.id, '', 'test_calls')['of'], 1)

    def test_finding_in_an_app(self):
        data = self.Ws.ws_finding(self.jobs_proven.id, 'test_jobs')
        self.assertEqual(data['name'], 'Jobs fact')
        self.assertEqual((data['review'], data['review_note'], data['run'], data['origin'], data['used_in']),
                         (False, '', False, '', ''))
        self.assertEqual(len(data['source_rows']), 1)
        # A lead, a finding on another app's topic and an unmarked one all stay out.
        self.assertFalse(self.Ws.ws_finding(self.jobs_lead.id, 'test_jobs'))
        self.assertFalse(self.Ws.ws_finding(self.jobs_proven.id, 'test_calls'))
        self.assertFalse(self.Ws.ws_finding(self.plain_proven.id, 'test_jobs'))
        # In the Library itself the same finding keeps its review flag.
        self.assertTrue(self.Ws.ws_finding(self.jobs_proven.id)['review'])

    def test_nothing_changes_from_inside_an_app(self):
        researcher = self.env['sediba.workspace'].with_user(self.researcher)
        self.assertFalse(self.Ws.ws_nav('test_jobs')['can_edit'])
        self.assertFalse(researcher.ws_nav('test_jobs')['can_edit'])
        self.assertTrue(researcher.ws_nav()['can_edit'])
        for ws in (self.Ws, researcher):
            with self.assertRaises(AccessError):
                ws.ws_set_review(self.jobs_proven.id, False, 'test_jobs')
            with self.assertRaises(AccessError):
                ws.ws_set_status(self.jobs_proven.id, 'lead', 'test_jobs')
            with self.assertRaises(AccessError):
                ws.ws_set_topic_ai(self.jobs_topic.id, True, 'test_jobs')
        self.assertFalse(self.jobs_topic.ai_allowed)
        # A reader changes nothing in the Library itself either.
        with self.assertRaises(AccessError):
            self.Ws.ws_set_review(self.jobs_proven.id, False)
        with self.assertRaises(AccessError):
            self.env['sediba.finding'].with_user(self.reader).create({'name': 'Mine', 'topic_id': self.jobs_topic.id})
