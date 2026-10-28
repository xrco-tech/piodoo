# -*- coding: utf-8 -*-
"""Chat2Work on WhatsApp, the CV link (WhatsApp template / SMS fallback) and
the public CV page."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from .test_chat2work_ussd import make_id, years_ago

WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'
SMS = 'odoo.addons.chat2work.models.chat2work_cv._send_sms'


def text(wa_id, body):
    return {'from': wa_id, 'id': 'wamid.%s' % body, 'type': 'text', 'text': {'body': body}}


def tap(wa_id, key):
    return {'from': wa_id, 'id': 'wamid.tap%s' % key, 'type': 'interactive',
            'interactive': {'type': 'button_reply', 'button_reply': {'id': 'c2w:' + key, 'title': key}}}


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workWhatsapp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['chat2work.wa.session']
        cls.Candidate = cls.env['chat2work.candidate']
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('chat2work.ussd_age_min', '18')
        ICP.set_param('chat2work.ussd_age_max', '34')
        ICP.set_param('chat2work.public_base_url', 'https://c2w.example')
        ICP.set_param('chat2work.wa_phone_number_id', '')

    def setUp(self):
        super().setUp()
        self.sent = []
        patcher = patch(WA, autospec=True, side_effect=self._fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)
        sms = patch(SMS, return_value=True)
        self.sms = sms.start()
        self.addCleanup(sms.stop)
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)

    def _fake_send(self, _self, recipient, content, account=None, log_body='', log_type='interactive'):
        self.sent.append(content)
        return {'success': True, 'message_id': 'wamid.out%d' % len(self.sent)}

    def chat(self, wa_id, *messages):
        handled = [self.Session.wa_handle(m, {}) for m in messages]
        return handled

    def test_ignores_unrelated_messages(self):
        self.assertEqual(self.chat('27820001001', text('27820001001', 'hello')), [False])
        self.assertFalse(self.sent)

    def test_trigger_matching(self):
        self.env['ir.config_parameter'].sudo().set_param('chat2work.wa_triggers', 'chat2work,jobs,sebenza,ispani')
        match = self.Session._match_trigger
        self.assertEqual(match('Hi Chat2Work FLYER'), 'FLYER')
        self.assertEqual(match('jobs'), '')
        self.assertEqual(match('Sebenza car'), 'CAR')
        self.assertEqual(match('Sawubona, ispani'), '')
        self.assertEqual(match('Ispani please'), '')         # not a known tag
        self.assertEqual(match('jobs in Durban'), '')
        for other in ('do you have any jobs?', 'I am a jobseeker', 'jobsearch', 'hello', 'Hi there', ''):
            self.assertIsNone(match(other), other)

    def test_jobs_mid_sentence_goes_to_chatbot(self):
        self.env['ir.config_parameter'].sudo().set_param('chat2work.wa_triggers', 'chat2work,jobs')
        wa = '27820001009'
        self.assertEqual(self.chat(wa, text(wa, 'do you have any jobs?')), [False])
        self.assertFalse(self.sent)

    def test_create_profile_sends_cv_button(self):
        wa = '27820001002'
        id_no = make_id(years_ago(24))
        self.chat(wa, text(wa, 'Hi Chat2Work FLYER'))
        first = self.sent[-1]['interactive']
        self.assertEqual(first['type'], 'button')
        self.assertEqual(first['header']['image']['link'],
                         'https://c2w.example/chat2work/static/src/img/wa_welcome.png')
        self.assertEqual([b['reply']['id'] for b in first['action']['buttons']], ['c2w:1', 'c2w:2', 'c2w:0'])
        self.chat(wa, tap(wa, '1'), tap(wa, '1'))          # Create profile, I agree
        self.assertIn('13-digit SA ID', self.sent[-1]['interactive']['body']['text'])
        self.chat(wa, text(wa, id_no))
        status = self.sent[-1]['interactive']
        self.assertEqual(status['type'], 'list')            # 5 options → list
        self.chat(wa, tap(wa, '1'), text(wa, 'yes'))        # Unemployed, typed "yes"
        cand = self.Candidate.search([('phone', '=', '+' + wa)])
        self.assertTrue(cand)
        self.assertEqual(cand.registered_via, 'whatsapp')
        self.assertEqual(cand.source_tag, 'FLYER')
        self.assertTrue(cand.whatsapp_opt_in)
        self.assertEqual(self.sent[-2]['type'], 'text')
        cta = self.sent[-1]['interactive']
        self.assertEqual(cta['type'], 'cta_url')
        self.assertEqual(cta['action']['parameters']['url'], cand._c2w_cv_url())
        self.assertEqual(cand.cv_link_state, 'wa_sent')
        self.assertFalse(self.Session.search([('wa_id', '=', wa)]))

    def test_invalid_choice_then_exit(self):
        wa = '27820001003'
        self.chat(wa, text(wa, 'chat2work'), text(wa, 'banana'))
        self.assertIn("didn't get that", self.sent[-1]['interactive']['body']['text'])
        self.chat(wa, text(wa, 'nope'), text(wa, 'still no'))
        self.assertEqual(self.sent[-1]['type'], 'text')
        self.assertIn('Send "Hi Chat2Work"', self.sent[-1]['text']['body'])

    def test_expired_button_tap_is_answered(self):
        wa = '27820001004'
        self.assertEqual(self.chat(wa, tap(wa, '1')), [True])
        self.assertIn('session expired', self.sent[-1]['text']['body'])

    def test_consent_declined_stores_nothing(self):
        wa = '27820001005'
        self.chat(wa, text(wa, 'Hi Chat2Work'), tap(wa, '1'), tap(wa, '2'))
        self.assertIn('Nothing was saved', self.sent[-1]['text']['body'])
        self.assertFalse(self.Candidate.search([('phone', '=', '+' + wa)]))


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workCvLink(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('chat2work.public_base_url', 'https://c2w.example')
        self.cand = self.env['chat2work.candidate'].create({'name': 'Thandi', 'phone': '+27820002001'})
        self.sms = patch(SMS, return_value=True).start()
        self.wa = patch(WA, return_value={'success': True, 'message_id': 'wamid.tpl1'}).start()
        self.addCleanup(patch.stopall)

    def _template(self):
        return self.env.ref('chat2work.wa_template_cv_link')

    def test_sms_when_not_on_whatsapp(self):
        self.cand._c2w_queue_cv_link()
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.assertEqual(self.cand.cv_link_state, 'sms_sent')
        body = self.sms.call_args.args[2]
        self.assertIn(self.cand._c2w_cv_url(), body)
        self.assertLessEqual(len(body), 160)
        self.wa.assert_not_called()

    def test_sms_while_template_not_approved(self):
        self.cand.whatsapp_opt_in = True
        self.cand._c2w_queue_cv_link()
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.assertEqual(self.cand.cv_link_state, 'sms_sent')

    def test_template_then_failed_status_falls_back_to_sms(self):
        self._template().sudo().write({'status': 'APPROVED'})
        self.cand.whatsapp_opt_in = True
        self.cand._c2w_queue_cv_link()
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.assertEqual(self.cand.cv_link_state, 'wa_sent')
        content = self.wa.call_args.args[1]
        self.assertEqual(content['template']['components'][0]['parameters'][0]['text'], self.cand.cv_token)
        self.sms.assert_not_called()
        self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.tpl1', 'is_incoming': False, 'message_type': 'template',
            'message_timestamp': fields.Datetime.now(),
        }).write({'message_status': 'failed'})
        self.assertEqual(self.cand.cv_link_state, 'sms_queued')
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.assertEqual(self.cand.cv_link_state, 'sms_sent')

    def test_undelivered_template_falls_back_after_timeout(self):
        self._template().sudo().write({'status': 'APPROVED'})
        self.cand.whatsapp_opt_in = True
        self.cand._c2w_queue_cv_link()
        Candidate = self.env['chat2work.candidate']
        Candidate._cron_send_cv_links()
        self.cand.cv_link_sent_at = fields.Datetime.now() - timedelta(minutes=20)
        Candidate._cron_send_cv_links()
        self.assertEqual(self.cand.cv_link_state, 'sms_sent')

    def test_delivered_template_stops_fallback(self):
        self._template().sudo().write({'status': 'APPROVED'})
        self.cand.whatsapp_opt_in = True
        self.cand._c2w_queue_cv_link()
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.tpl1', 'is_incoming': False, 'message_type': 'template',
            'message_timestamp': fields.Datetime.now(),
        }).write({'message_status': 'delivered'})
        self.assertEqual(self.cand.cv_link_state, 'wa_delivered')
        self.cand.cv_link_sent_at = fields.Datetime.now() - timedelta(minutes=20)
        self.env['chat2work.candidate']._cron_send_cv_links()
        self.sms.assert_not_called()

    def test_ussd_profile_queues_link(self):
        Session = self.env['chat2work.ussd.session']
        phone, sid = '+27820002002', 'ATUid_cvlink'
        id_no = make_id(years_ago(22))
        crumbs = []
        Session.ussd_handle(sid, '*1#', phone, '', '')
        for inp in ('1', '1', '2', id_no, '1', '1'):
            crumbs.append(inp)
            Session.ussd_handle(sid, '*1#', phone, '*'.join(crumbs), inp)
        cand = self.env['chat2work.candidate'].search([('phone', '=', phone)])
        self.assertEqual(cand.cv_link_state, 'queued')
        self.assertTrue(cand.cv_token)

    def test_expired_token_not_found(self):
        token = self.cand._c2w_ensure_token()
        Candidate = self.env['chat2work.candidate']
        self.assertEqual(Candidate._c2w_find_by_token(token), self.cand)
        self.cand.cv_token_expires = fields.Datetime.now() - timedelta(days=1)
        self.assertFalse(Candidate._c2w_find_by_token(token))
        self.assertFalse(Candidate._c2w_find_by_token('bad'))


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workCvPage(HttpCase):

    def setUp(self):
        super().setUp()
        self.cand = self.env['chat2work.candidate'].create({'name': 'Sipho Dlamini', 'phone': '+27820003001'})
        self.token = self.cand._c2w_ensure_token()

    def _csrf(self, html):
        marker = 'name="csrf_token" value="'
        start = html.index(marker) + len(marker)
        return html[start:html.index('"', start)]

    def test_page_and_upload_and_help(self):
        res = self.url_open('/cv/%s' % self.token)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Hi Sipho', res.text)
        self.assertIn('082****001', res.text)
        csrf = self._csrf(res.text)
        res = self.url_open('/cv/%s/upload' % self.token, data={'csrf_token': csrf},
                            files={'cv_file': ('my cv.pdf', b'%PDF-1.4 test', 'application/pdf')})
        self.assertEqual(res.status_code, 200)
        self.assertIn("received your CV", res.text)
        self.cand.invalidate_recordset()
        self.assertEqual(self.cand.cv_state, 'uploaded')
        self.assertEqual(self.cand.cv_attachment_id.res_id, self.cand.id)
        res = self.url_open('/cv/%s/upload' % self.token, data={'csrf_token': csrf},
                            files={'cv_file': ('virus.exe', b'MZ', 'application/octet-stream')})
        self.assertIn('Upload a PDF', res.text)
        res = self.url_open('/cv/%s/help' % self.token, data={'csrf_token': csrf})
        self.assertIn('agent will call you', res.text)
        self.cand.invalidate_recordset()
        self.assertEqual(self.cand.cv_state, 'help_requested')
        self.assertTrue(self.env['chat2work.callback.request'].search(
            [('candidate_id', '=', self.cand.id), ('channel', '=', 'cv_page')]))

    def test_build_cv(self):
        res = self.url_open('/cv/%s' % self.token)
        res = self.url_open('/cv/%s/build' % self.token, data={
            'csrf_token': self._csrf(res.text),
            'full_name': 'Sipho Dlamini', 'town': 'Soweto', 'summary': 'Reliable and friendly.',
            'edu_school_0': 'Orlando High', 'edu_qualification_0': 'Matric', 'edu_year_0': '2022',
            'job_role_0': 'Cashier', 'job_employer_0': 'Spar', 'job_dates_0': '2023 - 2024',
            'skills': 'customer service, cash handling', 'languages': 'English, isiZulu',
            'licence': 'Code 8 (B)',
        })
        self.assertIn('Your CV is ready', res.text)
        self.cand.invalidate_recordset()
        self.assertEqual(self.cand.cv_state, 'built')
        self.assertEqual(self.cand.cv_data['experience'][0]['employer'], 'Spar')
        self.assertTrue(self.cand.cv_attachment_id.raw)
        res = self.url_open('/cv/%s/download' % self.token)
        self.assertEqual(res.status_code, 200)

    def test_unknown_token(self):
        res = self.url_open('/cv/ABCDEFGHJK')
        self.assertEqual(res.status_code, 404)
        self.assertIn('This link has expired', res.text)
