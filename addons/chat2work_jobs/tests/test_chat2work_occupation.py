# -*- coding: utf-8 -*-
import json
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.chat2work_jobs.models.chat2work_occupation import clean_title, nqf_from_text

POST = 'odoo.addons.chat2work_jobs.models.chat2work_occupation.requests.post'


def ai_answer(code):
    response = MagicMock(status_code=200)
    response.json.return_value = {'stop_reason': 'end_turn',
                                  'content': [{'type': 'text', 'text': json.dumps({'code': code})}]}
    return response


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workOccupation(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Occupation = self.env['chat2work.occupation']
        self.Listing = self.env['chat2work.listing']
        self.source = self.env['chat2work.listing.source'].create({'name': 'Occupations'})
        self.unit = lambda code: self.Occupation.search([('code', '=', code)])
        self.env['chat2work.candidate'].search([]).write({'job_seeking': False})

    def _listing(self, title, **vals):
        return self.Listing.create(dict({'title': title, 'source_id': self.source.id}, **vals))

    def _candidate(self, phone, **vals):
        return self.env['chat2work.candidate'].create(dict({'name': phone, 'phone': phone, 'job_seeking': True}, **vals))

    def test_isco_list_is_loaded(self):
        self.assertEqual(self.Occupation.search_count([('level', '=', 4)]), 436)
        clerk = self.unit('4222')
        self.assertEqual(clerk.name, 'Contact Centre Information Clerks')
        self.assertEqual(clerk.parent_id.code, '422')
        self.assertEqual(clerk.display_name, '4222 Contact Centre Information Clerks')

    def test_codes_and_education_from_text(self):
        for value in ('4222', '2021-422201', '422201', ' 4222 '):
            self.assertEqual(self.Occupation._c2w_from_code(value), self.unit('4222'), value)
        for value in ('', '42', 'abc', '9999'):
            self.assertFalse(self.Occupation._c2w_from_code(value), value)
        cases = {'Matric': '4', 'Grade 12': '4', 'NQF 6': '6', 'NQF Level 7': '7', '5': '5', 'Diploma': '6',
                 "Bachelor's degree": '7', 'Grade 10': '3', 'PhD': '10', '': False, 'Driver licence': False}
        for value, expected in cases.items():
            self.assertEqual(nqf_from_text(value), expected, value)
        self.assertEqual(clean_title('Cashier - West Street, Durban'), 'cashier')
        self.assertEqual(clean_title('Junior Stock Clerk (12 months)'), 'stock clerk')

    def test_new_listing_is_coded_from_its_title(self):
        cashier = self._listing('Cashier - Carlswald, Midrand')
        self.assertEqual((cashier.occupation_id.code, cashier.occupation_source), ('5230', 'title'))
        self.assertEqual(cashier.field, 'retail', 'the broad type of work follows the occupation')
        forklift = self._listing('Forklift truck driver x2')
        self.assertEqual(forklift.occupation_id.code, '8344')
        self.assertFalse(self._listing('Multi Skilled Employee (Mall of Africa)').occupation_id)
        cashier.occupation_id = self.unit('5223')
        self.assertEqual(cashier.occupation_source, 'agent')

    def test_import_columns(self):
        self.source._import_csv(
            b'title,external_ref,ofo_code,nqf_min,education_required\n'
            b'Customer Service Representative,O1,2021-422201,Matric,yes\nCleaner,O2,,NQF 3,\n')
        one = self.Listing.search([('external_ref', '=', 'O1')])
        self.assertEqual((one.occupation_id.code, one.occupation_source, one.nqf_min, one.nqf_required),
                         ('4222', 'import', '4', True))
        two = self.Listing.search([('external_ref', '=', 'O2')])
        self.assertEqual((two.nqf_min, two.nqf_required), ('3', False))

    def test_ai_codes_what_the_title_cannot(self):
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', 'test-key')
        packer = self._listing('YES Product Development Intern', description='Packing and labelling stock.')
        vague = self._listing('FirstJob Learnership Programme 2026')
        def answer(*args, **kwargs):
            return ai_answer('9321' if 'Packing' in kwargs['json']['messages'][0]['content'] else 'none')
        with patch(POST, side_effect=answer) as post:
            self.Listing._cron_code_occupations()
        self.assertEqual(post.call_count, 2)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], 'claude-haiku-5-5')
        self.assertIn('4222 Contact Centre Information Clerks', body['system'][0]['text'])
        self.assertEqual(body['system'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual((packer.occupation_id.code, packer.occupation_source), ('9321', 'ai'))
        self.assertFalse(vague.occupation_id)
        self.assertTrue(vague.occupation_checked_at)
        with patch(POST) as post:
            self.Listing._cron_code_occupations()
        post.assert_not_called()  # asked once only
        with patch(POST, return_value=ai_answer('12')):  # not a real code: ignored
            vague.action_suggest_occupation()
        self.assertFalse(vague.occupation_id)

    def test_scoring_by_occupation(self):
        listing = self._listing('Customer Service Representative', occupation_id=self.unit('4222').id)
        call = self._candidate('+27820007001', field='call_centre')
        admin = self._candidate('+27820007002', field='admin')
        retail = self._candidate('+27820007003', field='retail')
        other = self._candidate('+27820007004', field='other')
        score, reasons = listing._c2w_work_fit(call)
        self.assertEqual(score, 3)
        self.assertIn('same occupation: Contact Centre Information Clerks', reasons)
        score, reasons = listing._c2w_work_fit(admin)  # receptionists share minor group 422
        self.assertEqual(score, 1)
        self.assertIn('related work', reasons[0])
        self.assertIsNone(listing._c2w_work_fit(retail))
        self.assertEqual(listing._c2w_work_fit(other), (0, []))

    def test_scoring_by_education(self):
        listing = self._listing('Customer Service Representative', occupation_id=self.unit('4222').id,
                                nqf_min='4')
        cand = self._candidate('+27820007011', field='call_centre', nqf_level='4')
        self.assertEqual(listing._c2w_work_fit(cand)[0], 4)
        cand.nqf_level = '3'
        score, reasons = listing._c2w_work_fit(cand)
        self.assertEqual(score, 2)
        self.assertIn('below the education asked for: Matric (NQF 4)', reasons)
        listing.nqf_required = True
        self.assertIsNone(listing._c2w_work_fit(cand))
        cand.nqf_level = False
        self.assertEqual(listing._c2w_work_fit(cand)[0], 3, 'unknown education counts for nothing')

    def test_suggestions_use_occupation(self):
        listing = self._listing('Customer Service Representative', occupation_id=self.unit('4222').id,
                                province_ids=[(6, 0, self.env['chat2work.province'].search([('code', '=', 'gauteng')]).ids)])
        call = self._candidate('+27820007021', field='call_centre', province='gauteng')
        retail = self._candidate('+27820007022', field='retail', province='gauteng')
        listing.action_mark_verified()
        self.assertIn(call, listing.match_ids.candidate_id)
        self.assertNotIn(retail, listing.match_ids.candidate_id)
        self.assertIn('same occupation', listing.match_ids.reason)


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workCvOccupation(TransactionCase):

    CV = {
        'full_name': 'Thandi Secret-Name', 'email': 'thandi@example.com', 'town': 'Soweto',
        'experience': [{'role': 'Cashier', 'employer': 'Shoprite', 'dates': '2021-2024', 'duties': 'Tills, cash up'},
                       {'role': 'Call centre agent', 'employer': 'Acme', 'dates': '2019', 'duties': 'Inbound calls'}],
        'education': [{'school': 'Soweto High', 'qualification': 'National Diploma: Retail', 'year': '2018'},
                      {'school': 'Soweto High', 'qualification': 'Matric', 'year': '2015'}],
    }

    def setUp(self):
        super().setUp()
        self.Occupation = self.env['chat2work.occupation']
        self.unit = lambda code: self.Occupation.search([('code', '=', code)])
        self.Candidate = self.env['chat2work.candidate']
        self.Candidate.search([]).write({'cv_data': False})
        self.cand = self.Candidate.create({'name': 'Thandi', 'phone': '+27820008001', 'field': 'retail'})
        self.cand.sudo().cv_data = self.CV

    def _ai(self, occupations, nqf):
        response = MagicMock(status_code=200)
        response.json.return_value = {'stop_reason': 'end_turn', 'content': [
            {'type': 'text', 'text': json.dumps({'occupations': occupations, 'nqf': nqf})}]}
        return response

    def test_ai_codes_the_cv_once_and_again_when_it_changes(self):
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', 'test-key')
        with patch(POST, return_value=self._ai(['5230', '9999', '4222'], '6')) as post:
            self.Candidate._c2w_cron_code_cvs()
        content = post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('Cashier', content)
        self.assertIn('National Diploma', content)
        for private in ('Secret-Name', 'thandi@example.com', 'Soweto High', 'Shoprite', '+2782'):
            self.assertNotIn(private, content)
        self.assertEqual(sorted(self.cand.cv_occupation_ids.mapped('code')), ['4222', '5230'])
        self.assertEqual((self.cand.nqf_level, self.cand.nqf_source), ('6', 'cv'))
        with patch(POST) as post:
            self.Candidate._c2w_cron_code_cvs()
        post.assert_not_called()
        self.cand.nqf_level = '7'  # an agent knows better
        self.assertEqual(self.cand.nqf_source, 'agent')
        self.cand.sudo().cv_data = dict(self.CV, summary='Updated')
        with patch(POST, return_value=self._ai(['5223'], '4')):
            self.Candidate._c2w_cron_code_cvs()
        self.assertEqual(self.cand.cv_occupation_ids.mapped('code'), ['5223'])
        self.assertEqual(self.cand.nqf_level, '7', "the agent's education is kept")

    def test_without_ai_uses_titles_and_qualifications(self):
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', '')
        with patch(POST) as post:
            self.Candidate._c2w_cron_code_cvs()
        post.assert_not_called()
        self.assertIn('5230', self.cand.cv_occupation_ids.mapped('code'))
        self.assertEqual(self.cand.nqf_level, '6')

    def test_cv_history_scores_highest(self):
        self.cand.with_context(c2w_from_cv=True).cv_occupation_ids = [(6, 0, self.unit('4222').ids)]
        source = self.env['chat2work.listing.source'].create({'name': 'CV'})
        listing = self.env['chat2work.listing'].create({'title': 'Agent', 'source_id': source.id,
                                                        'occupation_id': self.unit('4222').id})
        score, reasons = listing._c2w_work_fit(self.cand)
        self.assertEqual(score, 4)
        self.assertIn('has worked as: Contact Centre Information Clerks', reasons)
        self.assertFalse(self.cand.cv_occupations_by_agent)
        self.cand.cv_occupation_ids = [(6, 0, [])]
        self.assertTrue(self.cand.cv_occupations_by_agent)
