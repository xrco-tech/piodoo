# -*- coding: utf-8 -*-
"""Company docs: drafts, publishing, versions, who may write, and what an
app's Reference shows."""
from datetime import date

from freezegun import freeze_time

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


class DocsCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer = new_test_user(cls.env, 'sediba_writer', groups='base.group_user,sediba.group_writer',
                                   name='Thandi Writer')
        cls.researcher = new_test_user(cls.env, 'sediba_doc_researcher', groups='base.group_user,sediba.group_user',
                                       email=False)
        cls.reader = new_test_user(cls.env, 'sediba_doc_reader', groups='base.group_user,sediba.group_reader',
                                   name='Sipho Agent')
        cls.outsider = new_test_user(cls.env, 'sediba_doc_outsider', groups='base.group_user')
        cls.env['sediba.doc'].with_context(active_test=False).search([]).write({'parent_id': False})
        cls.env['sediba.doc'].with_context(active_test=False).search([]).unlink()
        Space = cls.env['sediba.space']
        cls.jobs = Space.search([('code', '=', 'test_jobs')]) or Space.create({'name': 'Jobs app', 'code': 'test_jobs'})
        cls.calls = Space.search([('code', '=', 'test_calls')]) or Space.create({'name': 'Calls app', 'code': 'test_calls'})
        cls.Doc = cls.env['sediba.doc'].with_user(cls.writer)
        cls.Ws = cls.env['sediba.workspace'].with_user(cls.writer)
        cls.ReaderWs = cls.env['sediba.workspace'].with_user(cls.reader)


@tagged('post_install', '-at_install')
class TestSedibaDocs(DocsCase):

    def test_new_doc_is_a_draft_owned_by_its_writer(self):
        doc = self.Doc.create({'name': 'About us'})
        self.assertEqual((doc.state, doc.owner_id, doc.read_again), ('draft', self.writer, '3'))
        self.assertFalse(doc.read_again_by or doc._published())

    @freeze_time('2026-11-19')
    def test_publishing_keeps_a_version_and_sets_the_date(self):
        doc = self.Doc.create({'name': 'About us', 'body': '<p>First</p>', 'question_ids': [
            (0, 0, {'name': 'Is it free?', 'answer': 'Yes.'})]})
        doc.action_publish()
        self.assertEqual((doc.state, doc.has_changes, len(doc.version_ids)), ('published', False, 1))
        self.assertEqual((doc.last_read_on, doc.read_again_by), (date(2026, 11, 19), date(2027, 2, 19)))
        version = doc._published()
        self.assertEqual((version.number, version.name, version.published_by), (1, 'About us', 'Thandi Writer'))
        self.assertEqual(version.questions, [{'name': 'Is it free?', 'answer': 'Yes.'}])
        doc.read_again = '12'
        self.assertEqual(doc.read_again_by, date(2027, 11, 19))

    def test_editing_a_published_doc_changes_nothing_outside_until_published(self):
        doc = self.Doc.create({'name': 'How we work', 'body': '<p>First</p>', 'space_ids': [(6, 0, self.jobs.ids)]})
        doc.action_publish()
        doc.write({'owner_id': self.writer.id, 'space_ids': [(6, 0, (self.jobs | self.calls).ids)]})
        self.assertFalse(doc.has_changes)  # properties are not the text
        doc.write({'name': 'How we work'})
        self.assertFalse(doc.has_changes)  # same title again
        doc.write({'body': '<p>Second</p>'})
        self.assertTrue(doc.has_changes)
        shown = self.ReaderWs.ws_doc(doc.id, 'test_jobs')
        self.assertIn('First', shown['body'])
        self.assertNotIn('Second', shown['body'])
        self.assertIn('Second', self.Ws.ws_doc(doc.id)['body'])
        doc.action_publish()
        self.assertFalse(doc.has_changes)
        self.assertIn('Second', self.ReaderWs.ws_doc(doc.id, 'test_jobs')['body'])
        self.assertEqual(sorted(doc.version_ids.mapped('number')), [1, 2])
        self.assertEqual(doc._published().number, 2)

    def test_questions_count_as_changes(self):
        doc = self.Doc.create({'name': 'FAQ', 'question_ids': [(0, 0, {'name': 'One?', 'answer': 'Yes.'})]})
        doc.action_publish()
        doc.question_ids.answer = 'No.'
        self.assertTrue(doc.has_changes)
        doc.action_publish()
        doc.question_ids.unlink()
        self.assertTrue(doc.has_changes)

    def test_take_down_read_again_and_restore(self):
        doc = self.Doc.create({'name': 'Policy', 'body': '<p>Old</p>', 'space_ids': [(6, 0, self.jobs.ids)],
                               'question_ids': [(0, 0, {'name': 'Q?', 'answer': 'A.'})]})
        with freeze_time('2026-01-10'):
            doc.action_publish()
        with freeze_time('2026-06-01'):
            self.assertTrue(self.Ws._doc_due(doc))
            doc.action_read_again()
            self.assertEqual(doc.read_again_by, date(2026, 9, 1))
            self.assertFalse(self.Ws._doc_due(doc))
        doc.write({'name': 'Policy, new', 'body': '<p>New</p>'})
        doc.question_ids.unlink()
        doc.action_publish()
        doc.action_restore(doc.version_ids.filtered(lambda v: v.number == 1))
        self.assertEqual((doc.name, doc.question_ids.mapped('name'), doc.has_changes), ('Policy', ['Q?'], True))
        self.assertIn('Old', doc.body)
        self.assertIn('New', doc._published().body)  # the apps still show version 2
        doc.action_take_down()
        self.assertEqual(doc.state, 'draft')
        self.assertFalse(doc._published() or doc.read_again_by)
        self.assertFalse(self.ReaderWs.ws_doc(doc.id, 'test_jobs'))
        self.assertEqual(len(doc.version_ids), 2)

    def test_pages_go_one_level_deep_and_follow_their_parent(self):
        parent = self.Doc.create({'name': 'How we work', 'space_ids': [(6, 0, self.jobs.ids)]})
        page = self.Doc.create({'name': 'Hours', 'parent_id': parent.id})
        self.assertEqual(page.space_ids, self.jobs)
        with self.assertRaises(ValidationError):
            self.Doc.create({'name': 'Too deep', 'parent_id': page.id})
        with self.assertRaises(ValidationError):
            parent.parent_id = self.Doc.create({'name': 'Other'})

    def test_who_may_do_what(self):
        doc = self.Doc.create({'name': 'About us'})
        # A researcher reads docs but does not write them; neither does a reader.
        for user in (self.researcher, self.reader):
            self.assertEqual(doc.with_user(user).name, 'About us')
            with self.assertRaises(AccessError):
                doc.with_user(user).name = 'Changed'
            with self.assertRaises(AccessError):
                self.env['sediba.doc'].with_user(user).create({'name': 'Mine'})
        with self.assertRaises(AccessError):
            self.env['sediba.doc'].with_user(self.outsider).search([])
        # A writer reads research but does not change it.
        topic = self.env['sediba.topic'].create({'name': 'A topic'})
        self.assertEqual(topic.with_user(self.writer).name, 'A topic')
        with self.assertRaises(AccessError):
            topic.with_user(self.writer).name = 'Changed'
        with self.assertRaises(AccessError):
            doc.unlink()  # writers archive, they do not delete


@tagged('post_install', '-at_install')
class TestSedibaDocsWorkspace(DocsCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.topic = cls.env['sediba.topic'].create({'name': 'USSD rules', 'space_ids': [(6, 0, cls.jobs.ids)]})
        finding = cls.env['sediba.finding'].create({'name': 'A rule', 'topic_id': cls.topic.id, 'source_ids': [
            (0, 0, {'name': 'Own page', 'kind': 'primary', 'says': 'It says so'})]})
        finding.write({'status': 'verified', 'checked_on': date(2026, 11, 18)})
        cls.hidden_topic = cls.env['sediba.topic'].create({'name': 'Only leads', 'space_ids': [(6, 0, cls.jobs.ids)]})
        cls.how = cls.Doc.create({'name': 'How we work', 'sequence': 1, 'summary': 'Day to day.',
                                  'body': '<p>We answer the phone.</p>', 'space_ids': [(6, 0, cls.jobs.ids)],
                                  'topic_ids': [(6, 0, (cls.topic | cls.hidden_topic).ids)]})
        cls.hours = cls.Doc.create({'name': 'Hours', 'sequence': 2, 'parent_id': cls.how.id})
        cls.faq = cls.Doc.create({'name': 'FAQ', 'sequence': 3, 'space_ids': [(6, 0, (cls.jobs | cls.calls).ids)],
                                  'question_ids': [(0, 0, {'name': 'Does it cost anything?', 'answer': 'No, it is free.'})]})
        cls.draft = cls.Doc.create({'name': 'Pricing', 'sequence': 4, 'space_ids': [(6, 0, cls.jobs.ids)]})
        (cls.how | cls.hours | cls.faq).action_publish()

    def test_nav_in_sediba(self):
        nav = self.Ws.ws_nav()
        self.assertEqual([(d['name'], [p['name'] for p in d['pages']]) for d in nav['docs']],
                         [('How we work', ['Hours']), ('FAQ', []), ('Pricing', [])])
        self.assertEqual((nav['doc_count'], nav['doc_review'], nav['can_write'], nav['can_edit']), (4, 1, True, False))
        self.assertTrue(nav['templates'])
        researcher = self.env['sediba.workspace'].with_user(self.researcher).ws_nav()
        self.assertEqual((researcher['can_write'], researcher['can_edit'], researcher['templates']), (False, True, []))

    def test_an_app_shows_only_its_published_docs(self):
        jobs = self.ReaderWs.ws_nav('test_jobs')
        self.assertEqual([(d['name'], [p['name'] for p in d['pages']]) for d in jobs['docs']],
                         [('How we work', ['Hours']), ('FAQ', [])])
        self.assertEqual((jobs['doc_count'], jobs['doc_review'], jobs['can_write']), (3, 0, False))
        self.assertEqual([d['name'] for d in self.ReaderWs.ws_nav('test_calls')['docs']], ['FAQ'])
        self.assertEqual(self.ReaderWs.ws_nav('no_such_app')['docs'], [])
        # A draft, and a doc marked for another app, stay out.
        self.assertFalse(self.ReaderWs.ws_doc(self.draft.id, 'test_jobs'))
        self.assertFalse(self.ReaderWs.ws_doc(self.how.id, 'test_calls'))
        # A page whose parent is not shown stands on its own.
        self.hours.space_ids = [(6, 0, self.calls.ids)]
        self.assertEqual(sorted(d['name'] for d in self.ReaderWs.ws_nav('test_calls')['docs']), ['FAQ', 'Hours'])
        self.assertFalse(self.ReaderWs.ws_doc(self.hours.id, 'test_calls')['parent'])

    def test_doc_page(self):
        data = self.Ws.ws_doc(self.how.id)
        self.assertEqual((data['name'], data['state'], data['owner'], data['spaces']),
                         ('How we work', 'published', 'Thandi Writer', ['Jobs app']))
        self.assertEqual([p['name'] for p in data['pages']], ['Hours'])
        self.assertEqual([t['name'] for t in data['topics']], ['USSD rules', 'Only leads'])
        self.assertEqual(len(data['versions']), 1)
        shown = self.ReaderWs.ws_doc(self.how.id, 'test_jobs')
        # In an app: no working details, and only topics the app shows.
        self.assertNotIn('state', shown)
        self.assertNotIn('versions', shown)
        self.assertEqual([t['name'] for t in shown['topics']], ['USSD rules'])
        self.assertEqual(self.ReaderWs.ws_doc(self.faq.id, 'test_calls')['questions'],
                         [{'name': 'Does it cost anything?', 'answer': 'No, it is free.'}])
        self.assertFalse(self.Ws.ws_doc(0))
        # An older version can be read in Sediba.
        self.how.body = '<p>We answer faster now.</p>'
        self.how.action_publish()
        first = self.how.version_ids.filtered(lambda v: v.number == 1)
        old = self.Ws.ws_doc(self.how.id, False, first.id)
        self.assertEqual(old['viewing']['number'], 1)
        self.assertIn('answer the phone', old['body'])

    def test_overview(self):
        overview = self.Ws.ws_overview()
        self.assertEqual(overview['docs'], {'published': 3, 'draft': 1, 'due': 0})
        self.assertEqual([(r['name'], r['pages']) for r in overview['doc_rows']],
                         [('How we work', 1), ('FAQ', 0), ('Pricing', 0)])
        self.assertEqual([(r['name'], r['kind']) for r in overview['doc_review']], [('Pricing', 'draft')])
        jobs = self.ReaderWs.ws_overview('test_jobs')
        self.assertEqual(jobs['docs'], {'published': 3, 'draft': 0, 'due': 0})
        self.assertEqual(jobs['doc_review'], [])
        self.assertEqual(sorted(c['name'] for c in jobs['doc_cards']), ['FAQ', 'Hours', 'How we work'])
        self.assertEqual(sorted((c['name'], c['new']) for c in jobs['doc_changed']),
                         [('FAQ', True), ('Hours', True), ('How we work', True)])

    def test_review_list(self):
        self.faq.body = '<p>More.</p>'
        with freeze_time('2030-01-01'):
            kinds = sorted((r['name'], r['kind']) for r in self.Ws._doc_review())
        self.assertEqual(kinds, [('FAQ', 'changes'), ('FAQ', 'due'), ('Hours', 'due'), ('How we work', 'due'),
                                 ('Pricing', 'draft')])

    def test_search(self):
        self.assertEqual(self.Ws.ws_docs()['total'], 4)
        self.assertEqual([r['name'] for r in self.Ws.ws_docs('cost anything')['rows']], ['FAQ'])
        self.assertEqual([r['name'] for r in self.Ws.ws_docs('PHONE')['rows']], ['How we work'])
        # In an app the search reads what is published, not the working text.
        self.how.body = '<p>We use a secret word.</p>'
        self.assertEqual(self.ReaderWs.ws_docs('secret', 'test_jobs')['total'], 0)
        self.assertEqual(self.ReaderWs.ws_docs('phone', 'test_jobs')['total'], 1)
        self.assertEqual(self.ReaderWs.ws_docs('', 'test_jobs')['total'], 3)

    def test_writing_from_the_screen(self):
        blank = self.Ws.ws_doc_edit(False, self.how.id, 'policy')
        self.assertEqual((blank['id'], blank['parent_id'], blank['space_ids'], blank['owner_id']),
                         (False, self.how.id, self.jobs.ids, self.writer.id))
        self.assertIn('The rule', blank['body'])
        self.assertIn([self.writer.id, 'Thandi Writer'], blank['choices']['owners'])
        self.assertEqual(self.Ws.ws_doc_edit(False, False, 'faq')['questions'], [{'name': '', 'answer': ''}])
        with self.assertRaises(UserError):
            self.Ws.ws_doc_save(False, {'name': '  '})
        doc_id = self.Ws.ws_doc_save(False, {
            'name': ' Refunds ', 'summary': 'When we pay back.', 'body': '<p>Never.</p>', 'owner_id': self.writer.id,
            'parent_id': self.how.id, 'space_ids': self.calls.ids, 'ai_allowed': False, 'public_allowed': True, 'read_again': '6',
            'questions': [{'name': 'Why?', 'answer': 'Because.'}, {'name': ' ', 'answer': 'Dropped: no question.'}]})
        doc = self.env['sediba.doc'].browse(doc_id)
        self.assertEqual((doc.name, doc.state, doc.parent_id, doc.space_ids, doc.ai_allowed, doc.read_again),
                         ('Refunds', 'draft', self.how, self.calls, False, '6'))
        self.assertEqual(doc.question_ids.mapped('name'), ['Why?'])
        edit = self.Ws.ws_doc_edit(doc_id)
        self.assertEqual((edit['name'], edit['questions']), ('Refunds', [{'name': 'Why?', 'answer': 'Because.'}]))
        self.assertTrue(doc.public_allowed)
        self.assertEqual((edit['ai_allowed'], edit['public_allowed']), (False, True))
        self.assertFalse(self.Ws.ws_doc_edit(False)['public_allowed'])      # off on a new doc
        # Save and publish in one go; saving the same text again is not a change.
        vals = {'name': 'Refunds', 'summary': 'When we pay back.', 'body': doc.body, 'owner_id': self.writer.id,
                'parent_id': self.how.id, 'space_ids': self.calls.ids, 'ai_allowed': False, 'public_allowed': True, 'read_again': '6',
                'questions': [{'name': 'Why?', 'answer': 'Because.'}]}
        self.Ws.ws_doc_save(doc_id, vals, True)
        self.assertEqual(doc.state, 'published')
        self.Ws.ws_doc_save(doc_id, vals)
        self.assertFalse(doc.has_changes)
        self.Ws.ws_doc_save(doc_id, dict(vals, questions=[{'name': 'Why not?', 'answer': 'Because.'}]))
        self.assertTrue(doc.has_changes)

    def test_buttons(self):
        self.assertEqual(self.Ws.ws_doc_do(self.draft.id, 'publish')['state'], 'published')
        self.assertEqual(self.Ws.ws_doc_do(self.draft.id, 'take_down')['state'], 'draft')
        self.assertFalse(self.Ws.ws_doc_do(self.draft.id, 'no_such_button'))
        with self.assertRaises(UserError):
            self.Ws.ws_doc_do(self.how.id, 'archive')  # it has a page
        self.assertTrue(self.Ws.ws_doc_do(self.draft.id, 'archive'))
        self.assertFalse(self.draft.active)
        self.assertEqual(self.Ws.ws_nav()['doc_count'], 3)

    def test_only_writers_change_docs_and_never_from_an_app(self):
        vals = {'name': 'Changed'}
        for ws in (self.ReaderWs, self.env['sediba.workspace'].with_user(self.researcher)):
            for call in (lambda: ws.ws_doc_edit(self.how.id), lambda: ws.ws_doc_save(self.how.id, vals),
                         lambda: ws.ws_doc_do(self.how.id, 'take_down'), lambda: ws.ws_doc_note_done(1)):
                with self.assertRaises(AccessError):
                    call()
        self.assertFalse(self.Ws.ws_nav('test_jobs')['can_write'])
        outsider = self.env['sediba.workspace'].with_user(self.outsider)
        for call in (lambda: outsider.ws_doc(self.how.id), outsider.ws_docs,
                     lambda: outsider.ws_doc_note(self.how.id, 'Hello')):
            with self.assertRaises(AccessError):
                call()

    def test_tell_the_owner(self):
        self.assertTrue(self.ReaderWs.ws_doc_note(self.how.id, ' The hours are wrong. ', 'test_jobs'))
        self.assertFalse(self.ReaderWs.ws_doc_note(self.how.id, '   ', 'test_jobs'))
        self.assertFalse(self.ReaderWs.ws_doc_note(self.draft.id, 'Cannot see this one', 'test_jobs'))
        note = self.how.note_ids
        self.assertEqual((note.name, note.author, note.space, note.done),
                         ('The hours are wrong.', 'Sipho Agent', 'Jobs app', False))
        self.assertEqual(self.Ws.ws_doc(self.how.id)['notes'][0]['text'], 'The hours are wrong.')
        self.assertIn(('How we work', 'note'), [(r['name'], r['kind']) for r in self.Ws._doc_review()])
        self.assertEqual(self.Ws.ws_doc_note_done(note.id)['notes'], [])
        self.assertTrue(note.done)
