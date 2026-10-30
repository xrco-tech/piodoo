# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

CSV = b"""title,external_ref,employer,province,field,requirements,closing_on
Call Centre Agent,A1,Acme,Gauteng,call centre,Matric and customer service,2099-01-01
Stock Clerk,A2,Acme,WC,warehouse,Forklift licence,2099-01-01
,A3,Acme,Gauteng,,,
"""


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workListing(TransactionCase):

    def setUp(self):
        super().setUp()
        self.source = self.env['chat2work.listing.source'].create({'name': 'Test'})
        self.Listing = self.env['chat2work.listing']
        self.Candidate = self.env['chat2work.candidate']

    def _listing(self, ref):
        return self.Listing.search([('source_id', '=', self.source.id), ('external_ref', '=', ref)])

    def _candidate(self, phone, **vals):
        return self.Candidate.create(dict({'name': phone, 'phone': phone, 'job_seeking': True}, **vals))

    def test_import_parses_and_skips_rows_without_title(self):
        summary = self.source._import_csv(CSV)
        self.assertIn('2 new', summary)
        self.assertIn('1 skipped', summary)
        self.assertEqual(self._listing('A1').province_ids.mapped('code'), ['gauteng'])
        self.assertEqual(self._listing('A1').field, 'call_centre')
        self.assertEqual(self._listing('A2').province_ids.mapped('code'), ['western_cape'])

    def test_import_several_provinces(self):
        self.source._import_csv(b'title,external_ref,province\nA,M1,"Gauteng; WC, Mars"\nB,M2,National\nC,M3,\n')
        self.assertEqual(sorted(self._listing('M1').province_ids.mapped('code')), ['gauteng', 'western_cape'])
        self.assertEqual(len(self._listing('M2').province_ids), 9)
        self.assertFalse(self._listing('M3').province_ids)
        self.assertIn('3 unchanged', self.source._import_csv(
            b'title,external_ref,province\nA,M1,"WC; Gauteng"\nB,M2,National\nC,M3,\n'))

    def test_listing_in_several_provinces_fits_any_of_them(self):
        self.source._import_csv(b'title,external_ref,province\nDriver,M4,"Gauteng; Limpopo"\n')
        listing = self._listing('M4')
        one = self._candidate('+27820005011', province='gauteng')
        two = self._candidate('+27820005012', province='limpopo')
        out = self._candidate('+27820005013', province='free_state')
        listing.action_suggest_candidates()
        self.assertIn(one, listing.match_ids.candidate_id)
        self.assertIn(two, listing.match_ids.candidate_id)
        self.assertNotIn(out, listing.match_ids.candidate_id)
        self.assertIn('same province', listing.match_ids.filtered(lambda m: m.candidate_id == two).reason)

    def test_next_step_follows_candidates_and_state(self):
        self.Candidate.search([]).write({'job_seeking': False})
        listing = self.Listing.create({'title': 'Clerk', 'source_id': self.source.id})
        self.assertEqual(listing.work_state, 'needs_candidates')
        cand = self._candidate('+27820005021')
        listing.action_suggest_candidates()
        self.assertEqual(listing.work_state, 'to_review')
        match = listing.match_ids.filtered(lambda m: m.candidate_id == cand)
        match.action_approve()
        self.assertEqual(listing.work_state, 'ready')
        match.action_reject()
        self.assertEqual(listing.work_state, 'needs_candidates')
        listing.state = 'closed'
        self.assertEqual(listing.work_state, 'closed')

    def test_board_shows_every_column(self):
        groups = self.Listing.read_group([('source_id', '=', self.source.id)], ['work_state'], ['work_state'])
        self.assertEqual(len(groups), 4)

    def test_reimport_updates_instead_of_duplicating(self):
        self.source._import_csv(CSV)
        first = self._listing('A1')
        self.assertIn('2 unchanged', self.source._import_csv(CSV))
        self.assertIn('1 updated', self.source._import_csv(CSV.replace(b'Matric and', b'Grade 12 and')))
        self.assertEqual(self._listing('A1'), first)
        self.assertIn('Grade 12', first.requirements)

    def test_no_reference_uses_employer_title_location(self):
        data = b"title,employer,location\nCleaner,Acme,Soweto\n"
        self.source._import_csv(data)
        self.assertIn('1 unchanged', self.source._import_csv(data))

    def test_missing_rows_only_close_when_asked(self):
        self.source._import_csv(CSV)
        one = b"title,external_ref\nCall Centre Agent,A1\n"
        self.source._import_csv(one)
        self.assertEqual(self._listing('A2').state, 'open')
        self.source._import_csv(one, close_missing=True)
        self.assertEqual(self._listing('A2').state, 'closed')

    def test_expired_listing_closes(self):
        past = fields.Date.today() - timedelta(days=1)
        listing = self.Listing.create({'title': 'Old', 'source_id': self.source.id, 'closing_on': past})
        self.Listing._cron_daily()
        self.assertEqual(listing.state, 'closed')

    def test_feed_requires_https(self):
        self.source.write({'kind': 'csv_feed', 'feed_url': 'http://example.com/a.csv'})
        with self.assertRaises(Exception):
            self.source._fetch_feed()

    def test_failed_feed_is_recorded_and_others_continue(self):
        self.source.write({'kind': 'csv_feed', 'feed_url': 'https://example.com/a.csv'})
        with patch('odoo.addons.chat2work_jobs.models.chat2work_listing.requests.get', side_effect=OSError('down')):
            self.Listing._cron_daily()
        self.assertIn('Failed', self.source.last_result)

    def test_feed_closes_what_it_no_longer_lists(self):
        self.source._import_csv(CSV)
        self.source.write({'kind': 'csv_feed', 'feed_url': 'https://example.com/a.csv'})
        response = MagicMock()
        response.raw.read.return_value = b"title,external_ref\nCall Centre Agent,A1\n"
        with patch('odoo.addons.chat2work_jobs.models.chat2work_listing.requests.get', return_value=response):
            self.source._fetch_feed()
        self.assertEqual(self._listing('A2').state, 'closed')

    def test_suggestions_follow_the_rules(self):
        self.source._import_csv(CSV)
        best = self._candidate('+27820005001', province='gauteng', field='call_centre', employment_status='unemployed')
        unknown = self._candidate('+27820005002')
        other_area = self._candidate('+27820005003', province='limpopo')
        self._candidate('+27820005004', province='gauteng', job_seeking=False)
        self._candidate('+27820005005', province='gauteng').write({'stage': 'placed'})
        listing = self._listing('A1')
        listing.action_suggest_candidates()
        ours = listing.match_ids.filtered(lambda m: m.candidate_id.phone.startswith('+2782000500'))
        self.assertEqual(ours.candidate_id, best | unknown)
        self.assertEqual(ours.sorted('score', reverse=True)[0].candidate_id, best)
        self.assertNotIn(other_area, listing.match_ids.candidate_id)
        self.assertIn('same province', ours.filtered(lambda m: m.candidate_id == best).reason)

    def test_cv_keywords_raise_the_score(self):
        self.source._import_csv(CSV)
        cand = self._candidate('+27820005006')
        with_cv = self._candidate('+27820005007')
        attachment = self.env['ir.attachment'].create({
            'name': 'cv.txt', 'raw': b'I have matric and five years in customer service at a bank.',
            'mimetype': 'text/plain', 'res_model': 'chat2work.candidate', 'res_id': with_cv.id,
        })
        with_cv.cv_attachment_id = attachment
        self.assertEqual(with_cv.cv_text_state, 'readable')
        listing = self._listing('A1')
        listing.action_suggest_candidates()
        scores = {m.candidate_id: m for m in listing.match_ids}
        self.assertGreater(scores[with_cv].score, scores[cand].score)
        self.assertIn('customer', scores[with_cv].reason)

    def test_rejected_candidate_is_not_suggested_again(self):
        self.source._import_csv(CSV)
        cand = self._candidate('+27820005008', province='gauteng')
        listing = self._listing('A1')
        listing.action_suggest_candidates()
        match = listing.match_ids.filtered(lambda m: m.candidate_id == cand)
        match.action_reject()
        listing.action_suggest_candidates()
        self.assertEqual(match.state, 'rejected')
        self.assertEqual(len(listing.match_ids.filtered(lambda m: m.candidate_id == cand)), 1)

    def test_erasing_a_candidate_removes_their_matches(self):
        self.source._import_csv(CSV)
        cand = self._candidate('+27820005009', province='gauteng')
        listing = self._listing('A1')
        listing.action_suggest_candidates()
        match = listing.match_ids.filtered(lambda m: m.candidate_id == cand)
        self.assertTrue(match)
        cand._c2w_erase()
        self.assertFalse(match.exists())
