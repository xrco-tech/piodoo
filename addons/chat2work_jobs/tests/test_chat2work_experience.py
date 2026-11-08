# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.chat2work_jobs.models.chat2work_experience import years_asked

from .test_chat2work_occupation import POST, ai_answer


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workExperience(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Listing = self.env['chat2work.listing']
        self.Candidate = self.env['chat2work.candidate']
        self.Occupation = self.env['chat2work.occupation']
        self.source = self.env['chat2work.listing.source'].create({'name': 'Experience'})
        self.Candidate.search([]).write({'job_seeking': False})

    def _listing(self, title, **vals):
        return self.Listing.create(dict({'title': title, 'source_id': self.source.id}, **vals))

    def _candidate(self, phone, **vals):
        return self.Candidate.create(dict({'name': phone, 'phone': phone, 'job_seeking': True,
                                           'field': 'retail'}, **vals))

    def test_years_read_from_text(self):
        cases = {
            "Minimum 2 years' experience in retail": (2, False),
            "3-5 years of relevant working experience": (3, False),
            "two (2) years experience as a cashier": (2, False),
            "Experience: 1 year": (1, False),
            "Experience in sales (minimum 2 years)": (2, False),
            "Grade 12 and 6 months experience": (1, False),
            "No experience required": (0, True),
            "Previous experience not necessary": (0, True),
            "We have over 10 years of experience in logistics": (0, False),
            "Our company brings 12 years experience. Requirements: 2 years experience": (2, False),
            "Matric and a valid driver's licence": (0, False),
            "6 months' experience as a cleaner an added advantage": (0, False),
            "1-2 years retail experience (advantage). Willing to work": (0, False),
            "Advantage: 1 year retail experience, Retail Business Management": (0, False),
            "Grade 12 with no experience, or Grade 10/NQF3 with 1 year experience": (0, False),
            "Grade 10/NQF 3 with 1 year related experience, or Grade 12 without.": (0, False),
            "YES4Youth Programme 2026 - 12-month work experience (Roodekop)": (0, False),
            "12-month workplace experience programme at BMW": (0, False),
            "Up to 1 year relevant experience. Aged 18-35": (0, False),
            "Grade 12; no minimum experience (1 year contact centre preferred)": (0, True),
            "Grade 12 / Matric 0-6 months retail experience": (0, False),
            "Minimum 6 months cashier/till-operations experience": (1, False),
            "Minimum 2 years' forklift driving experience": (2, False),
        }
        for text, expected in cases.items():
            self.assertEqual(years_asked(text), expected, text)

    def test_listing_experience_and_entry_level(self):
        cashier = self._listing('Cashier - Midrand', requirements="Matric. 2 years' cashier experience.")
        self.assertEqual((cashier.experience_years, cashier.entry_level), (2, False))
        learnership = self._listing('Retail Learnership (12 months)', requirements='Matric')
        self.assertEqual((learnership.experience_years, learnership.entry_level), (0, True))
        grad = self._listing('Graduate Programme', requirements='Degree and 3 years experience')
        self.assertFalse(grad.entry_level, 'asks for experience, so not entry-level')
        packer = self._listing('Packer', description='No experience needed, training provided.')
        self.assertTrue(packer.entry_level)
        # An agent's value is kept when the ad changes, until read again.
        cashier.experience_years = 0
        self.assertTrue(cashier.experience_fixed)
        cashier.requirements = "3 years experience"
        self.assertEqual(cashier.experience_years, 0)
        cashier.action_read_experience()
        self.assertEqual((cashier.experience_years, cashier.experience_fixed), (3, False))

    def test_import_columns(self):
        self.source._import_csv(
            b'title,external_ref,experience_years,entry_level,requirements\n'
            b'Cashier,E1,2,,No experience needed\nPicker,E2,,yes,\n')
        one = self.Listing.search([('external_ref', '=', 'E1')])
        self.assertEqual((one.experience_years, one.entry_level, one.experience_fixed), (2, False, True))
        two = self.Listing.search([('external_ref', '=', 'E2')])
        self.assertEqual((two.experience_years, two.entry_level), (0, True))

    def test_candidate_work_experience(self):
        cand = self._candidate('+27820007001')
        self.assertEqual(cand.work_experience, 'unknown')
        cand.sudo().cv_data = {'education': [{'qualification': 'Matric', 'year': '2024'}], 'experience': []}
        self.assertEqual(cand.work_experience, 'none')
        cand.sudo().cv_data = {'experience': [{'role': 'Cashier', 'duties': 'Till'}]}
        self.assertEqual(cand.work_experience, 'yes')
        other = self._candidate('+27820007002', employment_status='employed')
        self.assertEqual(other.work_experience, 'yes')

    def test_scoring(self):
        needs = self._listing('Cashier - Midrand', requirements="2 years' experience")
        entry = self._listing('Cashier Learnership')
        unknown = self._candidate('+27820007003')
        none = self._candidate('+27820007004')
        none.sudo().cv_data = {'education': [{'qualification': 'Matric'}]}
        worked = self._candidate('+27820007005')
        worked.sudo().cv_data = {'experience': [{'role': 'Cashier'}]}
        self.assertIsNone(needs._score_candidate(none), "known to have no experience: left out")
        s_unknown, why = needs._score_candidate(unknown)
        self.assertIn("asks for 2 years' experience", why)
        s_worked, why = needs._score_candidate(worked)
        self.assertIn('has work experience', why)
        self.assertGreater(s_worked, s_unknown)
        s_entry, why = entry._score_candidate(none)
        self.assertIn('entry-level role', why)
        self.assertGreater(s_entry, s_unknown, 'entry-level jobs rank above jobs asking for experience')
        self.assertNotIn('entry-level role', entry._score_candidate(worked)[1])

    def test_other_work_is_coded(self):
        cand = self._candidate('+27820007006', field='other', wanted_work='Security guard')
        listing = self._listing('Security Officer - Sandton',
                                occupation_id=self.Occupation.search([('code', '=', '5414')]).id)
        with patch(POST, return_value=ai_answer(listing.occupation_id.code)) as post:
            self.Candidate._c2w_cron_code_wanted()
        self.assertEqual(cand.wanted_occupation_id, listing.occupation_id)
        self.assertEqual(cand.wanted_coded, 'Security guard')
        self.assertIn(listing.occupation_id.code, cand._c2w_unit_groups())
        self.assertIn('same occupation', listing._score_candidate(cand)[1][0])
        with patch(POST) as post:
            self.Candidate._c2w_cron_code_wanted()
        post.assert_not_called()
        # New words clear the old occupation; an agent's pick is kept.
        cand.wanted_work = 'Chef'
        self.assertFalse(cand.wanted_occupation_id)
        cand.wanted_occupation_id = listing.occupation_id
        with patch(POST) as post:
            self.Candidate._c2w_cron_code_wanted()
        post.assert_not_called()
        self.assertEqual(cand.wanted_occupation_id, listing.occupation_id)
