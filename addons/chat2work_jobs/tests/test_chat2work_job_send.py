# -*- coding: utf-8 -*-

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .test_chat2work_job_comms import JobCommsCase


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workJobSend(JobCommsCase):

    def _wizard(self):
        return self.env['chat2work.job.send'].with_context(default_candidate_id=self.cand.id).create({})

    def _ours(self, status, days=1):
        self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.ours%s%s' % (status, days), 'is_incoming': False, 'message_type': 'text',
            'message_timestamp': fields.Datetime.now(), 'wa_id': '27820006001', 'message_status': status})

    def test_counts_and_default_jobs(self):
        self.assertEqual(self.cand.job_match_review_count, 2)
        self.assertEqual(self.cand.job_match_ready_count, 0)
        self.match.action_approve()
        self.assertEqual((self.cand.job_match_review_count, self.cand.job_match_ready_count), (1, 1))
        self.assertEqual(self._wizard().match_ids, self.match)

    def test_card_job_stats(self):
        stats = lambda: (self.cand.job_good_match_count, self.cand.job_sent_count, self.cand.job_opened_count)
        self.assertEqual(stats(), (0, 0, 0))
        self.match.action_approve()
        self.cand.invalidate_recordset()
        self.assertEqual(stats(), (1, 0, 0))
        self.match.write({'notify_state': 'sent', 'opened_at': fields.Datetime.now(), 'open_count': 3})
        self.cand.invalidate_recordset()
        self.assertEqual(stats(), (1, 1, 1))
        self.match.listing_id.state = 'closed'
        self.cand.invalidate_recordset()
        self.assertEqual(stats(), (0, 1, 1), 'closed listings no longer count as good matches')

    def test_recommendation_follows_engagement(self):
        recommend = self.cand._c2w_recommended_channel
        self.cand.registered_via = 'ussd'
        self.assertEqual(recommend()[0], 'sms', 'USSD sign-up, no WhatsApp history')
        self._ours('delivered')
        self.assertEqual(recommend(), ('sms', "Hasn't read our last 1 WhatsApp message"))
        self._ours('read', 2)
        self.assertEqual(recommend(), ('whatsapp', 'Reads our WhatsApp messages'))
        self._window()
        self.assertEqual(recommend()[0], 'whatsapp')
        self.assertIn('24 hours', recommend()[1])
        self.cand.whatsapp_opt_in = False
        self.assertEqual(recommend()[0], 'sms')

    def test_failed_whatsapp_recommends_sms(self):
        self.cand.registered_via = 'whatsapp'
        self.assertEqual(self.cand._c2w_recommended_channel()[0], 'whatsapp')
        self._ours('failed')
        self.assertEqual(self.cand._c2w_recommended_channel()[0], 'sms')

    def test_send_by_whatsapp_marks_sent_and_cron_skips_it(self):
        self._window()
        self.match.action_approve()
        wizard = self._wizard()
        self.assertEqual(wizard.recommended_channel, 'whatsapp')
        wizard.action_send()
        self.assertEqual(self.match.notify_state, 'sent')
        self.assertEqual(self.sent[0]['type'], 'interactive')
        self.sms.assert_not_called()
        self.assertTrue(self.cand.job_alert_at)
        self.Match._cron_send_job_alerts()
        self.assertEqual(len(self.sent), 1, 'already sent, so the hourly alert leaves it')
        self.assertEqual(self.cand.job_match_ready_count, 0)

    def test_agent_can_override_to_sms(self):
        self._window()
        self.match.action_approve()
        wizard = self._wizard()
        wizard.channel = 'sms'
        wizard.action_send()
        self.assertFalse(self.sent)
        self.sms.assert_called_once()
        self.assertIn('Call centre agent', self.sms.call_args[0][2])
        self.assertEqual(self.match.notify_state, 'sent')

    def test_whatsapp_not_allowed_without_opt_in_or_when_it_fails(self):
        self.match.action_approve()
        self.cand.whatsapp_opt_in = False
        wizard = self._wizard()
        self.assertEqual(wizard.channel, 'sms')
        wizard.channel = 'whatsapp'
        with self.assertRaises(UserError):
            wizard.action_send()
        self.cand.whatsapp_opt_in = True
        self.env['whatsapp.template'].sudo().search([('name', '=', 'chat2work_job_match')]).write({'status': 'PENDING'})
        wizard = self._wizard()
        wizard.channel = 'whatsapp'
        with self.assertRaises(UserError):  # outside the window and no approved template
            wizard.action_send()
        self.sms.assert_not_called()
        self.assertEqual(self.match.notify_state, 'queued')

    def test_review_from_the_candidate(self):
        self.match.action_approve()
        self.match2.action_reject()
        self.assertEqual(self.cand.job_match_review_count, 0)
        found = self.env['chat2work.candidate'].search([
            ('id', '=', self.cand.id),
            ('listing_match_ids', 'any', [('state', '=', 'approved'), ('notify_state', '!=', 'sent'),
                                          ('listing_id.state', '=', 'open')])])
        self.assertEqual(found, self.cand)
