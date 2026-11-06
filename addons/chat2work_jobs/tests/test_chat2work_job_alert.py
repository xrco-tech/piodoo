# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged

from .test_chat2work_job_comms import JobCommsCase, tap



@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workJobAlert(JobCommsCase):

    def setUp(self):
        super().setUp()
        self.sms_alert = self.sms
        self.env['chat2work.candidate'].search([('id', '!=', self.cand.id)]).write({'job_seeking': False})
        gauteng = self.env['chat2work.province'].search([('code', '=', 'gauteng')])
        self.cand.write({'field': 'call_centre', 'province': 'gauteng'})
        for listing in (self.listing, self.listing2):
            listing.write({'field': 'call_centre', 'province_ids': [(6, 0, gauteng.ids)],
                           'apply_url': 'https://jobs.example.com/apply/%d' % listing.id,
                           'closing_on': date.today() + timedelta(days=10)})

    def test_sms_text_is_one_plain_sms(self):
        self.listing.write({'title': 'Customer Service Representative – Inbound Sales (Soweto Branch) x2',
                            'employer': 'Very Long Employer Name (Pty) Ltd Trading As Something'})
        text = self.match._c2w_sms_text()
        self.assertLessEqual(len(text), 160, text)
        self.assertTrue(text.isascii(), text)
        self.assertTrue(text.startswith('Chat2Work: Hi Sipho, a job for you: Customer Service Representative'), text)
        self.assertIn('/j/%s Reply 1=good match, 2=not. STOP to opt out' % self.match.link_token, text)
        self.assertIn('Apply by ', text)

    def test_a_phone_number_is_not_a_name(self):
        self.cand.name = '0820006001'
        self.assertEqual(self.match._c2w_alert_parts()['name'], 'there')
        self.assertIn('Hi there, a job for you', self.match._c2w_sms_text())

    def test_top_jobs_pick_the_best_open_ones(self):
        top = self.Match._c2w_top_jobs(3)
        self.assertEqual(set(top[self.cand].ids), {self.match.id, self.match2.id})
        self.listing2.apply_url = False
        self.listing.closing_on = date.today() - timedelta(days=1)
        self.assertFalse(self.Match._c2w_top_jobs(3))
        self.listing.closing_on = False
        self.assertEqual(self.Match._c2w_top_jobs(1)[self.cand], self.match)
        self.assertFalse(self.Match._c2w_top_jobs(1, min_score=99))

    def test_send_top_jobs_by_sms_then_waits_a_day(self):
        sent, failed, waiting = self.Match._c2w_send_top_jobs(3)
        self.assertEqual((sent, failed, waiting), (2, 0, 0))
        self.assertEqual(self.sms_alert.call_count, 2)
        self.assertEqual(set((self.match | self.match2).mapped('notify_channel')), {'sms'})
        self.match2.notify_state = 'none'
        self.assertFalse(self.Match._c2w_top_jobs(3), 'nothing more within 24 hours')

    def test_whatsapp_waits_for_the_template_when_asked(self):
        self.cand.registered_via = 'whatsapp'
        self.assertEqual(self.Match._c2w_send_top_jobs(1, sms_fallback=False), (0, 0, 1))
        self.assertEqual(self.match.notify_state, 'none')
        self.sms_alert.assert_not_called()

    def test_whatsapp_buttons_feedback_and_stop(self):
        self._window()
        self.assertTrue(self.cand._c2w_send_job_listing(self.match))
        buttons = self.sent[-1]['interactive']['action']['buttons']
        self.assertEqual([b['reply']['id'] for b in buttons],
                         ['c2w:jf:good:%d' % self.match.id, 'c2w:jf:bad:%d' % self.match.id, 'c2w:jf:stop'])
        body = self.sent[-1]['interactive']['body']['text']
        for part in ('Hi Sipho', '💼 Call centre agent', '🏢 Acme', '📍 Soweto', '📅 Apply by', '/j/'):
            self.assertIn(part, body)
        Session = self.env['chat2work.wa.session']
        self.assertTrue(Session.wa_handle(tap('27820006001', 'c2w:jf:good:%d' % self.match.id), {}))
        self.assertEqual(self.match.feedback, 'good')
        self.assertIn('Good luck', self.sent[-1]['text']['body'])
        other = self.env['chat2work.candidate'].create({'name': 'Other', 'phone': '+27820006009'})
        Session.wa_handle(tap('27820006009', 'c2w:jf:bad:%d' % self.match.id), {})
        self.assertEqual(self.match.feedback, 'good', "someone else can't judge it")
        Session.wa_handle(tap('27820006001', 'c2w:jf:stop'), {})
        self.assertTrue(self.cand.job_alerts_stopped)
        self.assertFalse(self.cand._c2w_send_job_listing(self.match2))
        self.assertFalse(self.Match._c2w_top_jobs(3))
        Session.wa_handle({'from': '27820006001', 'id': 'wamid.st', 'type': 'text', 'text': {'body': 'START'}}, {})
        self.assertFalse(self.cand.job_alerts_stopped)
        self.assertTrue(other)

    def test_sms_replies(self):
        Bot = self.env['whatsapp.chatbot.message']
        self.cand._c2w_send_job_listing(self.match, channel='sms')
        self.assertTrue(Bot.process_incoming_sms_message('27820006001', ' 2. '))
        self.assertEqual(self.match.feedback, 'bad')
        self.assertIn('better matches', self.sms_alert.call_args.args[2])
        self.assertTrue(Bot.process_incoming_sms_message('+27820006001', 'STOP'))
        self.assertTrue(self.cand.job_alerts_stopped)
        self.assertTrue(Bot.process_incoming_sms_message('0820006001', 'start'))
        self.assertFalse(self.cand.job_alerts_stopped)
        with patch('odoo.addons.comm_whatsapp_chatbot.models.whatsapp_chatbot_message.WhatsAppChatbotMessage'
                   '.process_incoming_sms_message', autospec=True, return_value='bot') as bot:
            Bot.process_incoming_sms_message('27820006001', '1')  # nothing waiting for a verdict
        bot.assert_called_once()


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workJobLink(HttpCase):

    def test_link_counts_and_redirects(self):
        source = self.env['chat2work.listing.source'].create({'name': 'Links'})
        listing = self.env['chat2work.listing'].create({'title': 'Packer', 'source_id': source.id,
                                                        'apply_url': 'jobs.example.com/a?b=1'})
        cand = self.env['chat2work.candidate'].create({'name': 'Lindiwe', 'phone': '+27820006101'})
        match = self.env['chat2work.listing.match'].create({'listing_id': listing.id, 'candidate_id': cand.id})
        url = match._c2w_link()
        token = url.rsplit('/', 1)[1]
        res = self.url_open('/j/%s' % token, allow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers['Location'], 'https://jobs.example.com/a?b=1')
        self.url_open('/j/%s' % token.lower(), allow_redirects=False)
        match.invalidate_recordset()
        self.assertEqual(match.open_count, 2)
        self.assertTrue(match.opened_at)
        self.assertEqual(self.url_open('/j/AAAAAA', allow_redirects=False).status_code, 404)
        listing.apply_url = 'javascript:alert(1)'
        self.assertEqual(self.url_open('/j/%s' % token, allow_redirects=False).status_code, 404)
