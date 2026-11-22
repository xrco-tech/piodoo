# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.sediba.models.sediba_fact import _nice
from odoo.addons.sediba.models.sediba_flow import clean_doc, doc_parts, doc_text

VIS = '<div class="o_sdb_vis o_sdb_vis_%s_%s">anything</div>'


@tagged('post_install', '-at_install', 'sediba')
class TestSedibaVisual(TransactionCase):
    """Visual blocks: drawn only from facts on verified findings, each item
    naming its finding, and always readable as plain lines too."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.researcher = new_test_user(env, 'sediba_vis_researcher', groups='base.group_user,sediba.group_user')
        cls.writer = new_test_user(env, 'sediba_vis_writer', name='Naledi Dube',
                                   groups='base.group_user,sediba.group_writer')
        cls.reader = new_test_user(env, 'sediba_vis_reader', groups='base.group_user,sediba.group_reader')
        Space = env['sediba.space']
        cls.jobs = Space.search([('code', '=', 'test_jobs')]) or Space.create({'name': 'Jobs app', 'code': 'test_jobs'})
        cls.calls = Space.search([('code', '=', 'test_calls')]) or Space.create({'name': 'Calls app', 'code': 'test_calls'})
        Org = env['sediba.organisation']
        cls.zebra = Org.create({'name': 'Zebra Labs'})
        cls.okapi = Org.create({'name': 'Okapi AI'})
        cls.topic = env['sediba.topic'].create({
            'name': 'Zebra models', 'summary': 'One.\nTwo.', 'ai_allowed': True,
            'space_ids': [(6, 0, cls.jobs.ids)]})
        cls.soon = fields.Date.today() + timedelta(days=20)
        cls.past = fields.Date.today() - timedelta(days=20)
        price = 'Price per million tokens, US$'

        def finding(name, facts, proven=True, topic=None):
            record = env['sediba.finding'].create({
                'name': name, 'topic_id': (topic or cls.topic).id,
                'source_ids': [(0, 0, {'name': 'Own page', 'kind': 'primary', 'opened': True})],
                'fact_ids': [(0, 0, dict(fact, sequence=index)) for index, fact in enumerate(facts)]})
            if proven:
                record.write({'status': 'verified', 'checked_on': date(2026, 11, 20)})
            return record

        cls.prices = finding('Zebra prices', [
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Big', 'organisation_id': cls.zebra.id,
             'series': 'Input', 'value': 8, 'shown': '$8'},
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Big', 'organisation_id': cls.zebra.id,
             'series': 'Output', 'value': 40, 'shown': '$40'},
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Small', 'organisation_id': cls.zebra.id,
             'series': 'Input', 'value': 0.1, 'shown': 'from $0.10'},
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Small', 'organisation_id': cls.zebra.id,
             'series': 'Output', 'value': 0.5},
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Big', 'organisation_id': cls.zebra.id,
             'series': 'Cached', 'value': 1},
            {'kind': 'headline', 'label': 'Highest price found', 'shown': '$8 / $40', 'subject': 'Zebra Big',
             'organisation_id': cls.zebra.id},
        ])
        cls.okapi_facts = finding('Okapi One', [
            {'kind': 'measure', 'label': price, 'subject': 'Okapi One', 'organisation_id': cls.okapi.id,
             'series': 'Input', 'value': 2},
            {'kind': 'measure', 'label': price, 'subject': 'Okapi One', 'organisation_id': cls.okapi.id,
             'series': 'Output', 'value': 10},
            {'kind': 'tag', 'label': 'Open weights', 'subject': 'Okapi Free', 'organisation_id': cls.okapi.id},
            {'kind': 'tag', 'label': 'Free tier', 'organisation_id': cls.okapi.id},
            {'kind': 'tag', 'label': 'Under review', 'organisation_id': cls.okapi.id, 'action': True},
        ])
        cls.dates = finding('Zebra dates', [
            {'kind': 'date', 'label': 'Zebra Old shuts down', 'date': cls.soon, 'action': True,
             'organisation_id': cls.zebra.id},
            {'kind': 'date', 'label': 'Zebra Big released', 'date': cls.past, 'tag': 'Launch'},
            {'kind': 'date', 'label': 'Zebra Tiny ended', 'date': cls.past - timedelta(days=5), 'action': True},
        ])
        cls.rumour = finding('Zebra rumour', [
            {'kind': 'headline', 'label': 'Rumoured price', 'shown': '$99'},
            {'kind': 'measure', 'label': price, 'subject': 'Zebra Ghost', 'series': 'Output', 'value': 99},
            {'kind': 'date', 'label': 'Rumoured launch', 'date': cls.soon},
        ], proven=False)
        cls.Ws = env['sediba.workspace'].with_user(cls.researcher)

    def test_a_fact_must_be_complete(self):
        Fact = self.env['sediba.fact']
        base = {'finding_id': self.rumour.id, 'label': 'X'}
        for vals in ({'kind': 'headline'}, {'kind': 'measure', 'value': 1},
                     {'kind': 'measure', 'subject': 'A', 'value': -1}, {'kind': 'date'}):
            with self.assertRaises(ValidationError):
                Fact.create(dict(base, **vals))
        self.assertTrue(Fact.create(dict(base, kind='tag')))

    def test_scale_ends_on_a_round_number(self):
        self.assertEqual([_nice(v) for v in (0, 0.5, 3, 7.5, 40, 41, 950)], [1, 0.5, 4, 10, 40, 50, 1000])

    def test_only_verified_findings_are_drawn(self):
        v = self.Ws.ws_topic(self.topic.id)['visual']
        self.assertEqual([t['label'] for t in v['tiles']], ['Highest price found'])
        self.assertEqual(v['tiles'][0], {'label': 'Highest price found', 'figure': '$8 / $40',
                                         'about': 'Zebra Big, Zebra Labs', 'finding': self.prices.id})
        chart, = v['charts']
        self.assertNotIn('Zebra Ghost', [r['subject'] for r in chart['rows']])
        self.assertNotIn('Rumoured launch', [d['label'] for d in v['dates']])
        # Once the rumour is proven it is drawn.
        self.rumour.write({'status': 'verified', 'checked_on': date(2026, 11, 21)})
        again = self.Ws.ws_topic(self.topic.id)['visual']
        self.assertIn('Zebra Ghost', [r['subject'] for r in again['charts'][0]['rows']])
        self.assertEqual(len(again['tiles']), 2)

    def test_comparison_bars(self):
        chart, = self.Ws.ws_topic(self.topic.id)['visual']['charts']
        self.assertEqual(chart['label'], 'Price per million tokens, US$')
        # Two measures at most; the third is named, not drawn.
        self.assertEqual(chart['series'], ['Input', 'Output'])
        self.assertEqual(chart['left_out'], ['Cached'])
        # Sorted by the second measure, highest first, on one scale.
        self.assertEqual([r['subject'] for r in chart['rows']], ['Zebra Big', 'Okapi One', 'Zebra Small'])
        self.assertEqual(chart['sorted_by'], 'Output')
        self.assertEqual(chart['ticks'], ['0', '10', '20', '30', '40'])
        big, okapi, small = chart['rows']
        self.assertEqual([(b['series'], b['percent']) for b in big['bars']], [('Input', 20.0), ('Output', 100.0)])
        self.assertEqual([b['percent'] for b in okapi['bars']], [5.0, 25.0])
        # The value beside the row: as written, or the number when nothing was written.
        self.assertEqual((big['shown'], okapi['shown'], small['shown']), ('$8 / $40', '2 / 10', 'from $0.10 / 0.5'))
        self.assertEqual(big['org']['name'], 'Zebra Labs')
        self.assertEqual((big['org']['letter'], big['org']['has_logo']), ('Z', False))
        self.assertEqual(big['finding'], self.prices.id)
        # A thing the findings name but give no figure for is listed, not drawn.
        self.assertEqual(chart['not_drawn'], ['Okapi Free'])

    def test_dates_to_know(self):
        dates = self.Ws.ws_topic(self.topic.id)['visual']['dates']
        self.assertEqual([d['label'] for d in dates], ['Zebra Tiny ended', 'Zebra Big released', 'Zebra Old shuts down'])
        # Amber only for a date still ahead that needs action.
        self.assertEqual([d['act'] for d in dates], [False, False, True])
        self.assertEqual(dates[1]['tag'], 'Launch')
        self.assertTrue(all(d['finding'] == self.dates.id for d in dates))

    def test_organisation_cards(self):
        cards = {c['org']['name']: c for c in self.Ws.ws_topic(self.topic.id)['visual']['orgs']}
        self.assertEqual(set(cards), {'Zebra Labs', 'Okapi AI'})
        self.assertEqual(cards['Zebra Labs']['lines'], [
            {'subject': 'Zebra Big', 'shown': '$8 / $40'}, {'subject': 'Zebra Small', 'shown': 'from $0.10 / 0.5'}])
        self.assertEqual(len(cards['Zebra Labs']['tags']), 1)
        self.assertTrue(cards['Zebra Labs']['tags'][0]['act'])
        self.assertIn('Zebra Old shuts down', cards['Zebra Labs']['tags'][0]['label'])
        # A missing figure stays missing: never a guess.
        self.assertEqual(cards['Okapi AI']['lines'], [
            {'subject': 'Okapi One', 'shown': '2 / 10'}, {'subject': 'Okapi Free', 'shown': False}])
        # Two tags at most, what needs action first.
        self.assertEqual(cards['Okapi AI']['tags'], [
            {'label': 'Under review', 'act': True}, {'label': 'Open weights', 'act': False}])

    def test_a_logo_is_uploaded_once(self):
        pixel = b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
        self.zebra.logo = pixel
        v = self.Ws.ws_topic(self.topic.id)['visual']
        self.assertTrue(v['charts'][0]['rows'][0]['org']['has_logo'])
        self.assertTrue([c for c in v['orgs'] if c['org']['name'] == 'Zebra Labs'][0]['org']['has_logo'])

    def test_nothing_to_draw(self):
        bare = self.env['sediba.topic'].create({'name': 'Bare', 'summary': 'Words only.'})
        page = self.Ws.ws_topic(bare.id)
        self.assertFalse(page['visual'])
        self.assertEqual(page['summary'], ['Words only.'])

    def test_text_and_finding_page(self):
        topic = self.topic
        lines = topic._visual_lines(topic._visual())
        self.assertIn('Highest price found: $8 / $40 (Zebra Big, Zebra Labs)', lines)
        self.assertIn('Price per million tokens, US$ (Input / Output): Zebra Big, Zebra Labs: $8 / $40', lines)
        self.assertIn('Price per million tokens, US$: no figure found for Okapi Free.', lines)
        self.assertTrue(any(line.endswith('Zebra Old shuts down (Act before this)') for line in lines))
        self.assertTrue(any(line.startswith('Okapi AI: Okapi One 2 / 10; Okapi Free [no figure found]') for line in lines))
        facts = self.Ws.ws_finding(self.prices.id)['facts']
        self.assertEqual(facts[0], 'Zebra Big, Zebra Labs: Price per million tokens, US$, Input: $8')
        self.assertEqual(facts[-1], 'Highest price found: $8 / $40 (Zebra Big, Zebra Labs)')

    def test_inside_an_app(self):
        Ws = self.env['sediba.workspace'].with_user(self.reader)
        v = Ws.ws_topic(self.topic.id, '', 'test_jobs')['visual']
        self.assertEqual(len(v['charts'][0]['rows']), 3)
        self.assertFalse(Ws.ws_topic(self.topic.id, '', 'test_calls'))
        # Each block opens its finding, which the app shows too.
        self.assertTrue(Ws.ws_finding(v['tiles'][0]['finding'], 'test_jobs'))

    # ── In a company doc ─────────────────────────────────────────────────────

    def _doc(self, body, publish=True, **vals):
        Ws = self.env['sediba.workspace'].with_user(self.writer)
        doc_id = Ws.ws_doc_save(False, dict({
            'name': 'Zebra prices explained', 'body': body, 'flows': {}, 'space_ids': (self.jobs | self.calls).ids,
            'ai_allowed': True, 'read_again': '3'}, **vals), publish)
        return self.env['sediba.doc'].browse(doc_id)

    def test_block_in_a_doc(self):
        body = '<p>Before.</p><ul><li>In a list' + VIS % ('bars', self.topic.id) + '</li></ul><p>After.</p>'
        doc = self._doc(body + VIS % ('bars', 999999) + '<div class="o_sdb_vis o_sdb_vis_nonsense_1">x</div>')
        # One block, on its own line, holding only its class and a line of words.
        self.assertEqual(doc.body.count('o_sdb_vis_bars_%s' % self.topic.id), 1)
        self.assertNotIn('999999', doc.body)
        self.assertNotIn('nonsense', doc.body)
        self.assertIn('>Visual block: Comparison bars, Zebra models</div>', doc.body)
        # Saving again changes nothing.
        Ws = self.env['sediba.workspace'].with_user(self.writer)
        edit = Ws.ws_doc_edit(doc.id)
        self.assertIn(['bars', 'Comparison bars'], edit['choices']['visual_blocks'])
        self.assertIn([self.topic.id, 'Zebra models'], edit['choices']['visual_topics'])
        Ws.ws_doc_save(doc.id, dict(edit, body=str(edit['body'])), False)
        self.assertFalse(doc.has_changes)

        parts = Ws.ws_doc(doc.id)['parts']
        self.assertEqual(['visual' if 'visual' in p else 'html' for p in parts], ['html', 'visual', 'html'])
        block = parts[1]['visual']
        self.assertEqual((block['block'], block['topic'], block['can_open']), ('bars', [self.topic.id, 'Zebra models'], True))
        self.assertEqual(len(block['data']['charts']), 1)
        self.assertEqual((block['data']['tiles'], block['data']['dates'], block['data']['orgs']), ([], [], []))
        self.assertTrue(block['lines'])

        # In an app that shows the topic, the block opens its findings; in one that does not, it only shows.
        Reader = self.env['sediba.workspace'].with_user(self.reader)
        self.assertTrue(Reader.ws_doc(doc.id, 'test_jobs')['parts'][1]['visual']['can_open'])
        self.assertFalse(Reader.ws_doc(doc.id, 'test_calls')['parts'][1]['visual']['can_open'])

    def test_block_with_nothing_to_draw(self):
        bare = self.env['sediba.topic'].create({'name': 'Bare'})
        doc = self._doc('<p>Before.</p>' + VIS % ('all', bare.id))
        Ws = self.env['sediba.workspace'].with_user(self.writer)
        # The writer sees the block is empty; a reader in an app does not see it at all.
        self.assertFalse(Ws.ws_doc(doc.id)['parts'][1]['visual']['data'])
        Reader = self.env['sediba.workspace'].with_user(self.reader)
        self.assertEqual(len(Reader.ws_doc(doc.id, 'test_jobs')['parts']), 1)

    def test_pure_text_handling(self):
        body = '<p>Before.</p>' + VIS % ('dates', 7) + '<p>After.</p>'
        self.assertEqual(clean_doc(body, {})[0], '<p>Before.</p><p>After.</p>')
        kept = clean_doc(body, {}, lambda block, topic_id: 'Dates of topic %s' % topic_id)[0]
        self.assertIn('<div class="o_sdb_vis o_sdb_vis_dates_7">Dates of topic 7</div>', kept)
        self.assertEqual(doc_parts(kept, {})[1], {'visual': {'block': 'dates', 'topic_id': 7}})
        self.assertEqual(doc_text(kept, {}), 'Before.\n\nAfter.')
        self.assertEqual(doc_text(kept, {}, lambda block, topic_id: 'LINES'), 'Before.\n\nLINES\n\nAfter.')

    def test_assistants_follow_the_topic_switch(self):
        doc = self._doc('<p>Zebraworks price notes.</p>' + VIS % ('all', self.topic.id), public_allowed=True)
        Assistant = self.env['sediba.assistant']

        def text(public=False):
            found = Assistant.look_up('Zebraworks price notes', public=public)['results']
            return [item for item in found if item['title'] == doc.name][0]['text']

        # Sidekick may read the topic, so it reads the block as lines.
        self.assertIn('Zebra Big, Zebra Labs: $8 / $40', text())
        # The public chatbot may read the doc but not the topic: the block says nothing to it.
        self.assertNotIn('Zebra Big', text(public=True))
        self.topic.public_allowed = True
        self.assertIn('Zebra Big, Zebra Labs: $8 / $40', text(public=True))
        self.topic.ai_allowed = False
        self.assertNotIn('Zebra Big', text())
