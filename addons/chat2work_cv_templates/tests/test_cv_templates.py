# -*- coding: utf-8 -*-
"""Every design renders the candidate's answers, whatever they filled in."""

from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import file_open

FULL = {
    'full_name': 'Nomvula Ntšoane-Dlamini', 'email': 'nomvula@example.com', 'town': 'Soweto',
    'summary': 'Reliable and friendly.', 'skills': 'Forklift, Excel; first aid',
    'languages': 'English, isiZulu', 'licence': 'Code 10 (C1)',
    'education': [{'school': 'Morris Isaacson', 'qualification': 'Matric', 'year': '2021'}],
    'experience': [{'role': 'Cashier', 'employer': 'Shoprite', 'dates': '2022 – 2024',
                    'duties': 'Handled cash. Helped customers.'}],
}


@tagged('post_install', '-at_install', 'chat2work')
class TestCvTemplates(TransactionCase):

    def setUp(self):
        super().setUp()
        self.cand = self.env['chat2work.candidate'].create({'name': 'Nomvula', 'phone': '+27820004001'})
        self.templates = self.env['chat2work.cv.template'].search([])

    def _html(self, details, template=None):
        self.cand.write({'cv_data': details, 'cv_template_id': template.id if template else False})
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'chat2work.action_report_cv', self.cand.ids)
        return html.decode()

    def test_at_least_ten_designs(self):
        self.assertGreaterEqual(len(self.templates), 10)

    def test_every_design_has_a_preview(self):
        for template in self.templates:
            with file_open('chat2work_cv_templates/static/src/img/%s.png' % template.key, 'rb') as image:
                self.assertTrue(image.read(8))

    def test_every_design_shows_every_answer(self):
        for template in self.templates:
            html = self._html(FULL, template)
            for text in ('Nomvula Ntšoane-Dlamini', 'nomvula@example.com', 'Soweto', 'Reliable and friendly.',
                         'Forklift', 'first aid', 'isiZulu', 'Code 10 (C1)', 'Morris Isaacson', 'Matric',
                         'Cashier', 'Shoprite', 'Handled cash', 'Helped customers', 'Available on request'):
                self.assertIn(text, html, '%s lost %s' % (template.key, text))

    def test_every_design_copes_with_only_a_name(self):
        for template in self.templates:
            html = self._html({'full_name': 'Sipho'}, template)
            self.assertIn('Sipho', html)
            for heading in ('Work Experience', 'Education', 'Skills', 'Profile', "Driver's Licence"):
                self.assertNotIn('>%s<' % heading, html, template.key)

    def test_answers_are_escaped(self):
        for template in self.templates:
            html = self._html({'full_name': '<script>x</script>', 'skills': '<img src=x>'}, template)
            self.assertNotIn('<script>x', html)
            self.assertNotIn('<img src=x>', html)

    def test_no_licence_is_left_out(self):
        self.assertEqual(self.cand.write({'cv_data': dict(FULL, licence='None')}) and self.cand._c2w_cv_view()['licence'], '')

    def test_retired_design_falls_back(self):
        template = self.templates[-1]
        self.cand.cv_template_id = template
        self.assertEqual(self.cand._c2w_cv_layout(), template.layout)
        template.active = False
        self.assertEqual(self.cand._c2w_cv_layout(), self.templates[0].layout)

    def test_public_choice_is_validated(self):
        template = self.templates[1]
        for bad in (None, '', 'abc', '-1', '999999999'):
            self.cand._c2w_set_cv_template(bad)
            self.assertFalse(self.cand.cv_template_id)
        self.cand._c2w_set_cv_template(str(template.id))
        self.assertEqual(self.cand.cv_template_id, template)

    def test_duties_become_bullets(self):
        self.cand.cv_data = FULL
        self.assertEqual(self.cand._c2w_cv_view()['experience'][0]['duties'], ['Handled cash', 'Helped customers'])


@tagged('post_install', '-at_install', 'chat2work')
class TestCvPagePicker(HttpCase):

    def test_page_offers_the_designs(self):
        cand = self.env['chat2work.candidate'].create({'name': 'Thabo', 'phone': '+27820004002'})
        token = cand._c2w_ensure_token()
        res = self.url_open('/cv/%s' % token)
        self.assertEqual(res.status_code, 200)
        self.assertIn('name="cv_template"', res.text)
        for template in self.env['chat2work.cv.template'].search([]):
            self.assertIn(template.name, res.text)
