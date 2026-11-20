# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install', 'sediba')
class TestSedibaAssistant(TransactionCase):
    """What Sidekick and a chatbot may read: published docs that allow it and
    verified findings on topics that allow it. Nothing else, whoever asks."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Space = env['sediba.space']
        cls.jobs = Space.search([('code', '=', 'test_jobs')]) or Space.create({'name': 'Jobs app', 'code': 'test_jobs'})
        cls.calls = Space.search([('code', '=', 'test_calls')]) or Space.create({'name': 'Calls app', 'code': 'test_calls'})
        Doc = env['sediba.doc']
        cls.about = Doc.create({'name': 'About Zebraworks', 'summary': 'Who we are.',
                                'body': '<p>Zebraworks helps people find <b>work</b> by phone.</p>',
                                'space_ids': [(6, 0, (cls.jobs | cls.calls).ids)]})
        cls.faq = Doc.create({'name': 'Zebra FAQ', 'space_ids': [(6, 0, cls.jobs.ids)], 'question_ids': [
            (0, 0, {'name': 'Does it cost money?', 'answer': 'No. Zebraworks is free for job seekers.'}),
            (0, 0, {'name': 'Which languages?', 'answer': 'English and isiZulu.'})]})
        cls.private = Doc.create({'name': 'Zebra salaries', 'body': '<p>Zebraworks pays its staff well.</p>',
                                  'ai_allowed': False, 'space_ids': [(6, 0, cls.jobs.ids)]})
        cls.draft = Doc.create({'name': 'Zebra plans', 'body': '<p>Zebraworks will open in Durban.</p>'})
        (cls.about | cls.faq | cls.private).action_publish()

        Topic = env['sediba.topic']
        cls.open_topic = Topic.create({'name': 'Zebra market', 'ai_allowed': True, 'space_ids': [(6, 0, cls.jobs.ids)],
                                       'our_read': 'Zebraworks should hurry.'})
        cls.shut_topic = Topic.create({'name': 'Zebra rivals', 'space_ids': [(6, 0, cls.jobs.ids)]})

        def finding(name, topic, statement, proven=False):
            record = env['sediba.finding'].create({
                'name': name, 'topic_id': topic.id, 'statement': statement,
                'source_ids': [(0, 0, {'name': 'Stats SA', 'kind': 'primary', 'opened': True})]})
            if proven:
                record.write({'status': 'verified', 'checked_on': fields.Date.today()})
            return record

        cls.proven = finding('Zebra youth unemployment', cls.open_topic, 'Youth unemployment is high for zebras.', True)
        cls.lead = finding('Zebra rumour', cls.open_topic, 'Zebras may get a subsidy.')
        cls.shut = finding('Zebra rival prices', cls.shut_topic, 'A rival charges zebras a fee.', True)
        cls.outsider = new_test_user(env, 'sediba_assist_outsider', groups='base.group_user')
        cls.Assistant = env['sediba.assistant'].with_user(cls.outsider)

    def _titles(self, question, space=False):
        return self.Assistant.look_up(question, space)['used']

    def test_only_published_and_allowed_docs(self):
        titles = self._titles('zebraworks')
        self.assertIn('About Zebraworks', titles)
        self.assertIn('Zebra FAQ', titles)
        self.assertNotIn('Zebra salaries', titles)      # switched off
        self.assertNotIn('Zebra plans', titles)         # a draft
        self.private.ai_allowed = True
        self.assertIn('Zebra salaries', self._titles('zebraworks'))
        self.about.action_take_down()
        self.assertNotIn('About Zebraworks', self._titles('zebraworks'))

    def test_the_published_version_not_the_working_copy(self):
        self.about.body = '<p>Zebraworks is closing down.</p>'
        result = self.Assistant.look_up('zebraworks phone')['results']
        about = next(item for item in result if item['title'] == 'About Zebraworks')
        self.assertIn('by phone', about['text'])
        self.assertNotIn('closing', about['text'])
        self.assertNotIn('<', about['text'])

    def test_only_verified_findings_on_allowed_topics(self):
        self.assertEqual(self._titles('zebras'), ['Zebra youth unemployment'])
        item = self.Assistant.look_up('zebras')['results'][0]
        self.assertEqual((item['topic'], item['sources']), ('Zebra market', ['Stats SA']))
        self.assertNotIn('hurry', str(self.Assistant.look_up('zebraworks hurry')))     # our read stays out
        self.shut_topic.ai_allowed = True
        self.assertIn('Zebra rival prices', self._titles('zebras'))
        self.open_topic.ai_allowed = False
        self.assertNotIn('Zebra youth unemployment', self._titles('zebras'))

    def test_an_app_gets_only_what_its_reference_shows(self):
        self.assertEqual(self._titles('zebraworks', 'test_calls'), ['About Zebraworks'])
        self.assertEqual(self._titles('zebras', 'test_calls'), [])
        self.assertEqual(self._titles('zebras', 'test_jobs'), ['Zebra youth unemployment'])

    def test_the_answers_that_fit_and_the_index(self):
        result = self.Assistant.look_up('does it cost money')
        faq = next(item for item in result['results'] if item['title'] == 'Zebra FAQ')
        self.assertEqual(faq['questions'][0]['answer'], 'No. Zebraworks is free for job seekers.')
        self.assertEqual(self.Assistant.source_label(result), 'Sediba: Zebra FAQ')
        nothing = self.Assistant.look_up('quantum giraffes')
        self.assertEqual((nothing['results'], self.Assistant.source_label(nothing)), ([], ''))
        self.assertTrue(nothing['note'])
        index = self.Assistant.look_up('')
        self.assertIn('Zebra FAQ', [doc['title'] for doc in index['docs']])
        self.assertNotIn('Zebra plans', [doc['title'] for doc in index['docs']])
        self.assertIn({'topic': 'Zebra market', 'verified_findings': 1}, index['research_topics'])
        self.assertEqual(self.Assistant.tool()['name'], 'look_up_reference')

    def test_the_public_chatbot_has_its_own_switch(self):
        """What Sidekick may read says nothing about what the public may be told."""
        public = lambda question: self.Assistant.look_up(question, public=True)['used']
        self.assertEqual(public('zebraworks'), [])
        self.assertEqual(public('zebras'), [])
        self.assertTrue(self.Assistant.look_up('', public=True)['note'])
        self.faq.public_allowed = True
        self.private.public_allowed = True          # public, though Sidekick is not allowed it
        self.draft.public_allowed = True            # still a draft
        self.assertEqual(sorted(public('zebraworks')), ['Zebra FAQ', 'Zebra salaries'])
        self.assertNotIn('Zebra salaries', self._titles('zebraworks'))
        self.shut_topic.public_allowed = True
        self.lead.topic_id.public_allowed = False
        self.assertEqual(public('zebras'), ['Zebra rival prices'])
        self.assertEqual(self._titles('zebras'), ['Zebra youth unemployment'])
