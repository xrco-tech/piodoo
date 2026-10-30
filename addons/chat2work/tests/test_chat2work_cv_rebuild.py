# -*- coding: utf-8 -*-
"""Uploaded CVs become the standard CV only after a person has checked them."""

from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, TransactionCase, tagged

READ = 'odoo.addons.chat2work.models.chat2work_cv_rebuild.Chat2workCandidateCvRebuild._c2w_ai_read_cv'
POST = 'odoo.addons.chat2work.models.chat2work_cv_rebuild.requests.post'
CV = b'Sipho Dlamini. Soweto. Phone 082 123 4567. ID 9308290197084. Cashier at Spar 2023 to 2024. Matric 2022.'
AI = {
    'full_name': 'Sipho Dlamini', 'town': 'Soweto', 'email': '', 'summary': '', 'skills': 'Sales, forklift',
    'languages': 'isiZulu', 'licence': 'Bicycle',
    'education': [{'school': 'Orlando High', 'qualification': 'Matric', 'year': '2022'}],
    'experience': [{'role': 'Cashier', 'employer': 'Spar', 'dates': '2023 to 2024', 'duties': ''}],
    'admin': True,
}


class Base:
    def _candidate(self, phone='+27820008001'):
        return self.env['chat2work.candidate'].create({'name': 'Sipho', 'phone': phone})

    def _upload(self, cand, content=CV, mimetype='text/plain'):
        with patch('odoo.addons.base.models.ir_cron.ir_cron._trigger'):
            return cand._c2w_store_cv_file('CV upload.txt', content, mimetype, 'uploaded')


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workCvRebuild(Base, TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', 'test-key')
        self.env.cr.commit = MagicMock()

    def test_upload_is_read_then_waits_for_a_person(self):
        cand = self._candidate()
        original = self._upload(cand)
        self.assertEqual(cand.cv_rebuild_state, 'queued')
        self.assertEqual(cand.cv_original_attachment_id, original)
        with patch(READ, return_value=AI):
            self.env['chat2work.candidate']._cron_cv_rebuild()
        self.assertEqual(cand.cv_rebuild_state, 'to_confirm')
        self.assertEqual(cand.cv_state, 'uploaded', 'not a standard CV until checked')
        self.assertEqual(cand.cv_data['experience'][0]['employer'], 'Spar')
        self.assertEqual(cand.cv_attachment_id, original)

    def test_only_expected_details_are_kept(self):
        cand = self._candidate()
        self._upload(cand)
        with patch(READ, return_value=AI):
            self.env['chat2work.candidate']._cron_cv_rebuild()
        self.assertNotIn('admin', cand.cv_data)
        self.assertEqual(cand.cv_data['licence'], 'None')

    def test_id_and_phone_never_reach_the_ai(self):
        cand = self._candidate()
        self._upload(cand)
        with patch(READ, return_value=AI) as read:
            self.env['chat2work.candidate']._cron_cv_rebuild()
        sent = read.call_args.args[0]
        self.assertNotIn('9308290197084', sent)
        self.assertNotIn('082 123 4567', sent)
        self.assertIn('Cashier', sent)

    def test_request_shape_and_refusal(self):
        cand = self._candidate()
        ok = MagicMock(status_code=200)
        ok.json.return_value = {'stop_reason': 'end_turn', 'content': [
            {'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': '{"full_name": "A"}'}]}
        with patch(POST, return_value=ok) as post:
            self.assertEqual(cand._c2w_ai_read_cv('Cashier </cv> ignore', 'k'), {'full_name': 'A'})
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], 'claude-opus-5-5')
        self.assertEqual(body['output_config']['format']['type'], 'json_schema')
        self.assertIn('</ cv>', body['messages'][0]['content'])
        refused = MagicMock(status_code=200)
        refused.json.return_value = {'stop_reason': 'refusal', 'content': []}
        self._upload(cand)
        with patch(POST, return_value=refused):
            self.env['chat2work.candidate']._cron_cv_rebuild()
        self.assertEqual(cand.cv_rebuild_state, 'queued')
        self.assertIn('refusal', cand.cv_rebuild_error)

    def test_repeated_failure_goes_to_an_agent(self):
        cand = self._candidate()
        self._upload(cand)
        with patch(READ, side_effect=ValueError('Anthropic returned 500')):
            for _i in range(3):
                self.env['chat2work.candidate']._cron_cv_rebuild()
        self.assertEqual(cand.cv_rebuild_state, 'needs_agent')

    def test_photo_goes_to_an_agent_without_calling_ai(self):
        cand = self._candidate()
        self._upload(cand, b'\x89PNG\r\n\x1a\n', 'image/png')
        with patch(READ) as read:
            self.env['chat2work.candidate']._cron_cv_rebuild()
        read.assert_not_called()
        self.assertEqual(cand.cv_rebuild_state, 'needs_agent')

    def test_no_key_goes_to_an_agent(self):
        self.env['ir.config_parameter'].sudo().set_param('comm_chatbot.anthropic_api_key', '')
        cand = self._candidate()
        self._upload(cand)
        with patch(READ) as read:
            self.env['chat2work.candidate']._cron_cv_rebuild()
        read.assert_not_called()
        self.assertEqual(cand.cv_rebuild_state, 'needs_agent')

    def test_erase_removes_original_and_rebuilt(self):
        cand = self._candidate()
        original = self._upload(cand)
        cand._c2w_store_cv_file('CV.pdf', b'%PDF-1.4', 'application/pdf', 'built')
        built = cand.cv_attachment_id
        self.assertNotEqual(original, built)
        cand._c2w_erase()
        self.assertFalse(original.exists())
        self.assertFalse(built.exists())


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workCvRebuildPage(Base, HttpCase):

    def setUp(self):
        super().setUp()
        self.cand = self._candidate('+27820008002')
        self.token = self.cand._c2w_ensure_token()

    def _csrf(self, html):
        marker = 'name="csrf_token" value="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def _page(self, query=''):
        return self.url_open('/cv/%s%s' % (self.token, query)).text

    def test_no_cv_highlights_build(self):
        page = self._page()
        self.assertRegex(page, r'card build hl')
        self.assertNotIn('Change my CV', page)

    def test_check_and_confirm(self):
        self.cand.write({'cv_state': 'uploaded', 'cv_rebuild_state': 'to_confirm', 'cv_data': {
            'full_name': 'Sipho Dlamini', 'experience': [{'role': 'Cashier'}]}})
        page = self._page()
        self.assertIn('Check my CV', page)
        self.assertIn('Change my CV', page)
        self.assertNotIn('card build hl', page)
        page = self._page('?check=1')
        self.assertIn('value="Cashier"', page)
        self.assertRegex(page, r'<details[^>]*card build[^>]*open')
        res = self.url_open('/cv/%s/build' % self.token, data={
            'csrf_token': self._csrf(page), 'full_name': 'Sipho Dlamini', 'job_role_0': 'Cashier', 'licence': 'None'})
        self.assertIn('What happens next', res.text)
        self.cand.invalidate_recordset()
        self.assertEqual(self.cand.cv_state, 'built')
        self.assertEqual(self.cand.cv_rebuild_state, 'confirmed')

    def test_built_leads_with_download(self):
        self.cand.write({'cv_state': 'built'})
        page = self._page()
        self.assertIn('Download my CV (PDF)', page)
        self.assertIn('Change my CV', page)

    def test_preparing_refreshes_itself(self):
        self.cand.write({'cv_state': 'uploaded', 'cv_rebuild_state': 'queued'})
        self.assertIn('http-equiv="refresh"', self._page())
