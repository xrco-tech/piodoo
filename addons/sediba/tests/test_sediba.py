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
