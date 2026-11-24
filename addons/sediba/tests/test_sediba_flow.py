# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.sediba.models.sediba_flow import clean_doc, clean_steps, doc_parts, doc_text, flow_lines, flow_text

BLOCK = '<div class="o_sdb_flow o_sdb_flow_%s">anything</div>'


def steps():
    """A job seeker gets help: one decision, two ends."""
    return [
        {'id': 1, 'kind': 'start', 'text': 'Job seeker messages', 'detail': '', 'next': [{'label': '', 'to': 2}]},
        {'id': 2, 'kind': 'decision', 'text': 'Can the chatbot answer it?', 'detail': '',
         'next': [{'label': 'yes', 'to': 3}, {'label': 'no', 'to': 4}]},
        {'id': 3, 'kind': 'step', 'text': 'Chatbot answers', 'detail': 'From Library only', 'next': [{'label': '', 'to': 5}]},
        {'id': 4, 'kind': 'handover', 'text': 'Hand over to an agent', 'detail': '', 'next': []},
        {'id': 5, 'kind': 'end', 'text': 'Done', 'detail': '', 'next': []},
    ]


@tagged('post_install', '-at_install', 'sediba')
class TestSedibaFlow(TransactionCase):
    """Flow diagrams in a company doc: stored with the doc, published with
    it, and always also plain numbered steps."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer = new_test_user(cls.env, 'sediba_flow_writer', name='Naledi Dube',
                                   groups='base.group_user,sediba.group_writer')
        cls.reader = new_test_user(cls.env, 'sediba_flow_reader', groups='base.group_user,sediba.group_reader')
        cls.Ws = cls.env['sediba.workspace'].with_user(cls.writer)
        Space = cls.env['sediba.space']
        cls.jobs = Space.search([('code', '=', 'test_jobs')]) or Space.create({'name': 'Jobs app', 'code': 'test_jobs'})

    def _save(self, doc_id=False, body=None, flows=None, publish=False, **vals):
        body = body if body is not None else '<p>Before.</p>' + BLOCK % 'f1' + '<p>After.</p>'
        flows = flows if flows is not None else {'f1': {'name': 'Getting help', 'steps': steps()}}
        doc_id = self.Ws.ws_doc_save(doc_id, dict(
            {'name': 'How we work', 'body': body, 'flows': flows, 'space_ids': self.jobs.ids,
             'ai_allowed': True, 'read_again': '3'}, **vals), publish)
        return self.env['sediba.doc'].browse(doc_id)

    # ── The steps and their text ─────────────────────────────────────────────

    def test_as_text(self):
        flow = {'name': 'Getting help', 'steps': steps()}
        self.assertEqual([(line['label'], line['text']) for line in flow_lines(flow)], [
            ('Start', 'Job seeker messages. Then step 2.'),
            ('Decision', 'Can the chatbot answer it? If yes, step 3. If no, step 4.'),
            ('Step', 'Chatbot answers. From Library only. Then step 5.'),
            ('Hand-over', 'Hand over to an agent.'),
            ('End', 'Done.'),
        ])
        text = flow_text(flow)
        self.assertTrue(text.startswith('Flow diagram: Getting help\n1. Start: Job seeker messages.'))
        self.assertIn('\n5. End: Done.', text)
        # The editor's "As text" tab shows the same words.
        self.assertEqual(self.Ws.ws_flow_text(flow), flow_lines(flow))
        with self.assertRaises(AccessError):
            self.env['sediba.workspace'].with_user(self.reader).ws_flow_text(flow)

    def test_steps_are_cleaned(self):
        cleaned = clean_steps([
            {'id': '1', 'kind': 'nonsense', 'text': '  Two   words ', 'next': [{'to': 2}, {'to': 3}]},
            {'id': 2, 'kind': 'end', 'text': 'Stop', 'next': [{'to': 1}]},
            {'id': 2, 'kind': 'step', 'text': 'Same number again'},
            {'id': 3, 'kind': 'decision', 'text': 'Which?', 'next': [
                {'label': ' yes ', 'to': 99}, {'label': 'no', 'to': 3}, {'label': 'maybe', 'to': '1'}, 'junk']},
            {'kind': 'step', 'text': 'No number'}, 'junk',
        ])
        self.assertEqual([step['id'] for step in cleaned], [1, 2, 3])
        self.assertEqual((cleaned[0]['kind'], cleaned[0]['text']), ('step', 'Two words'))
        self.assertEqual(cleaned[0]['next'], [{'label': '', 'to': 2}])         # one way on, unless it is a decision
        self.assertEqual(cleaned[1]['next'], [])                               # an end leads nowhere
        self.assertEqual(cleaned[2]['next'], [{'label': 'yes', 'to': False},   # no such step
                                              {'label': 'no', 'to': False},    # itself
                                              {'label': 'maybe', 'to': 1}])
        undecided = flow_lines({'steps': cleaned})[2]['text']
        self.assertIn('If yes: not decided yet.', undecided)
        self.assertIn('If maybe, step 1.', undecided)

    def test_blocks_and_diagrams_are_kept_in_step(self):
        flows = {'f1': {'name': 'One', 'steps': steps()}, 'f2': {'name': 'Never placed', 'steps': []},
                 'BAD KEY': {'name': 'x', 'steps': []}}
        body = ('<p>Top</p><ul><li>In a list ' + BLOCK % 'f1' + ' still</li></ul>'
                + BLOCK % 'f1' + BLOCK % 'gone' + '<p>End</p>')
        cleaned, kept = clean_doc(body, flows)
        self.assertEqual(list(kept), ['f1'])
        self.assertEqual(cleaned.count('o_sdb_flow_f1'), 1)
        self.assertNotIn('o_sdb_flow_gone', cleaned)
        self.assertIn('Flow diagram: One (5 steps)', cleaned)
        # Lifted out of the list, onto a line of its own.
        self.assertLess(cleaned.index('</ul>'), cleaned.index('o_sdb_flow_f1'))
        self.assertIn('In a list', cleaned)
        self.assertIn('still', cleaned)
        parts = doc_parts(cleaned, kept)
        self.assertEqual(['flow' if 'flow' in part else 'html' for part in parts], ['html', 'flow', 'html'])
        self.assertEqual(parts[1]['flow']['key'], 'f1')
        self.assertEqual(len(parts[1]['flow']['lines']), 5)
        text = doc_text(cleaned, kept)
        self.assertIn('Top', text)
        self.assertIn('2. Decision: Can the chatbot answer it? If yes, step 3. If no, step 4.', text)
        self.assertLess(text.index('In a list'), text.index('Flow diagram: One'))
        self.assertLess(text.index('5. End: Done.'), text.index('End', text.index('5. End: Done.') + 12))
        # A doc with no diagram is left exactly as it was written.
        plain = '<p>Just   text</p>'
        self.assertEqual(clean_doc(plain, {}), (plain, {}))
        self.assertEqual(len(doc_parts(plain, {})), 1)
        self.assertEqual(doc_parts('<p><br></p>', {}), [])

    # ── In a doc ─────────────────────────────────────────────────────────────

    def test_saved_read_and_edited_with_the_doc(self):
        doc = self._save()
        self.assertEqual(list(doc.flows), ['f1'])
        self.assertEqual(len(doc.flows['f1']['steps']), 5)
        self.assertEqual(doc.body.count('o_sdb_flow_f1'), 1)
        page = self.Ws.ws_doc(doc.id)
        self.assertEqual(['flow' if 'flow' in part else 'html' for part in page['parts']], ['html', 'flow', 'html'])
        self.assertEqual(page['parts'][1]['flow']['name'], 'Getting help')
        self.assertIn('Before.', page['parts'][0]['html'])
        edit = self.Ws.ws_doc_edit(doc.id)
        self.assertEqual(edit['flows']['f1']['name'], 'Getting help')
        self.assertIn('o_sdb_flow_f1', edit['body'])
        # Found by the words of a step.
        self.assertEqual(self.Ws.ws_docs('hand over to an agent')['total'], 1)
        self.assertEqual(self.Ws.ws_docs('giraffe')['total'], 0)
        # Taking the block out of the text takes the diagram with it.
        self._save(doc.id, body='<p>Only words now.</p>')
        self.assertFalse(doc.flows)
        self.assertEqual(len(self.Ws.ws_doc(doc.id)['parts']), 1)
        self.assertEqual(self.Ws.ws_doc_edit(False)['flows'], {})
        with self.assertRaises(AccessError):
            self.env['sediba.workspace'].with_user(self.reader).ws_doc_save(False, {'name': 'x', 'flows': {}})

    def test_published_versions_keep_their_own_diagram(self):
        doc = self._save(publish=True)
        self.assertFalse(doc.has_changes)
        # Saving the same doc again is not a change.
        stored = doc.body
        self._save(doc.id, body=doc.body, flows=doc.flows)
        self.assertEqual(doc.body, stored)
        self.assertFalse(doc.has_changes)
        changed = steps()
        changed[3]['text'] = 'Hand over to a team leader'
        self._save(doc.id, body=doc.body, flows={'f1': {'name': 'Getting help', 'steps': changed}})
        self.assertTrue(doc.has_changes)
        reader = self.env['sediba.workspace'].with_user(self.reader)
        shown = [part['flow'] for part in reader.ws_doc(doc.id, 'test_jobs')['parts'] if 'flow' in part][0]
        self.assertEqual(shown['steps'][3]['text'], 'Hand over to an agent')       # the app still shows what was published
        working = [part['flow'] for part in self.Ws.ws_doc(doc.id)['parts'] if 'flow' in part][0]
        self.assertEqual(working['steps'][3]['text'], 'Hand over to a team leader')
        first = doc._latest()
        doc.action_publish()
        shown = [part['flow'] for part in reader.ws_doc(doc.id, 'test_jobs')['parts'] if 'flow' in part][0]
        self.assertEqual(shown['steps'][3]['text'], 'Hand over to a team leader')
        # An older version shows, and brings back, the diagram it was published with.
        old = [part['flow'] for part in self.Ws.ws_doc(doc.id, False, first.id)['parts'] if 'flow' in part][0]
        self.assertEqual(old['steps'][3]['text'], 'Hand over to an agent')
        self.Ws.ws_doc_do(doc.id, 'restore', first.id)
        self.assertEqual(doc.flows['f1']['steps'][3]['text'], 'Hand over to an agent')
        self.assertTrue(doc.has_changes)

    def test_the_assistants_read_the_steps(self):
        doc = self._save(publish=True)
        Assistant = self.env['sediba.assistant'].with_user(self.reader)
        result = Assistant.look_up('what happens when the chatbot cannot answer hand over agent')
        item = next(item for item in result['results'] if item['title'] == 'How we work')
        self.assertIn('Flow diagram: Getting help', item['text'])
        self.assertIn('4. Hand-over: Hand over to an agent.', item['text'])
        self.assertIn('Before.', item['text'])
        # A change that is not published yet does not reach them.
        changed = steps()
        changed[3]['text'] = 'Hand over to a robot'
        self._save(doc.id, body=doc.body, flows={'f1': {'name': 'Getting help', 'steps': changed}})
        self.assertNotIn('robot', str(Assistant.look_up('hand over agent robot')))
