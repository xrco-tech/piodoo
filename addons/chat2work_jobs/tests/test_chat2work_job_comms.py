# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'
SMS = 'odoo.addons.chat2work_jobs.models.chat2work_job_alert._send_sms'
HOURS = 'odoo.addons.chat2work_jobs.models.chat2work_job_comms.Chat2workListingMatchComms._c2w_in_send_hours'


def tap(wa_id, key):
    return {'from': wa_id, 'id': 'wamid.%s' % key, 'type': 'interactive',
            'interactive': {'type': 'list_reply', 'list_reply': {'id': key, 'title': key}}}


class JobCommsCase(TransactionCase):
    """A candidate with two suggested matches on verified listings; sends are faked."""

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('chat2work.wa_phone_number_id', '')
        self.sent = []
        patch(WA, autospec=True, side_effect=self._fake_send).start()
        self.sms = patch(SMS, return_value=True).start()
        patch(HOURS, return_value=True).start()
        self.addCleanup(patch.stopall)
        source = self.env['chat2work.listing.source'].create({'name': 'Test'})
        Listing = self.env['chat2work.listing']
        self.listing = Listing.create({'title': 'Call centre agent', 'source_id': source.id,
                                       'location': 'Soweto', 'employer': 'Acme'})
        self.listing2 = Listing.create({'title': 'Packer', 'source_id': source.id, 'location': 'Midrand'})
        (self.listing | self.listing2).action_mark_verified()
        self.cand = self.env['chat2work.candidate'].create({
            'name': 'Sipho Ndlovu', 'phone': '+27820006001', 'whatsapp_opt_in': True, 'job_seeking': True})
        Match = self.env['chat2work.listing.match']
        self.match = Match.create({'listing_id': self.listing.id, 'candidate_id': self.cand.id})
        self.match2 = Match.create({'listing_id': self.listing2.id, 'candidate_id': self.cand.id})
        self.Match = Match

    def _fake_send(self, _self, recipient, content, account=None, log_body='', log_type='interactive'):
        self.sent.append(content)
        return {'success': True, 'message_id': 'wamid.jobout%d' % len(self.sent)}

    def _window(self):
        self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.recent%s' % self.cand.id, 'is_incoming': True, 'message_type': 'text',
            'message_timestamp': fields.Datetime.now(), 'wa_id': '27820006001'})


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workJobComms(JobCommsCase):

    def test_good_match_queues_and_undo_unqueues(self):
        self.match.action_approve()
        self.assertEqual(self.match.notify_state, 'queued')
        self.match.action_reject()
        self.assertEqual(self.match.notify_state, 'none')
        self.Match._cron_send_job_alerts()
        self.assertFalse(self.sent)
        self.sms.assert_not_called()

    def test_one_alert_covers_waiting_matches_then_waits(self):
        self._window()
        (self.match | self.match2).action_approve()
        self.Match._cron_send_job_alerts()
        self.assertEqual(len(self.sent), 2, 'one message per job')
        self.assertEqual({m['interactive']['body']['text'].split('💼 ')[1].split('\n')[0] for m in self.sent},
                         {'Call centre agent', 'Packer'})
        self.assertEqual(set((self.match | self.match2).mapped('notify_state')), {'sent'})
        self.assertTrue(self.cand.job_alert_at)
        third = self.Match.create({'listing_id': self.env['chat2work.listing'].create({
            'title': 'Driver', 'source_id': self.listing.source_id.id}).id, 'candidate_id': self.cand.id})
        third.listing_id.action_mark_verified()
        third.action_approve()
        self.Match._cron_send_job_alerts()
        self.assertEqual(len(self.sent), 2, 'one alert every few days')
        self.assertEqual(third.notify_state, 'queued')
        self.cand.job_alert_at = fields.Datetime.now() - timedelta(days=4)
        self.Match._cron_send_job_alerts()
        self.assertEqual(third.notify_state, 'sent')

    def test_sms_when_not_on_whatsapp_or_no_template(self):
        self.match.action_approve()
        self.Match._cron_send_job_alerts()  # on WhatsApp but no window and no approved template
        self.assertIn('Call centre agent at Acme, Soweto', self.sms.call_args.args[2])
        self.assertEqual(self.match.notify_state, 'sent')

    def test_template_outside_the_window(self):
        tpl = self.env.ref('chat2work_jobs.wa_template_job_alert')
        tpl.status = 'APPROVED'
        self.cand.registered_via = 'whatsapp'
        self.match.action_approve()
        self.Match._cron_send_job_alerts()
        comps = self.sent[0]['template']['components']
        self.assertEqual([p['text'] for p in comps[0]['parameters']][:5],
                         ['Sipho', 'Call centre agent', 'Acme', 'Soweto', 'See the link'])
        self.assertIn('/j/', comps[0]['parameters'][5]['text'])
        self.assertEqual([c['parameters'][0]['payload'] for c in comps[1:]],
                         ['c2w:jf:good:%d' % self.match.id, 'c2w:jf:bad:%d' % self.match.id, 'c2w:jf:stop'])
        self.sms.assert_not_called()

    def test_closed_listing_is_not_sent(self):
        self.match.action_approve()
        self.listing.state = 'closed'
        self.Match._cron_send_job_alerts()
        self.assertEqual(self.match.notify_state, 'cancelled')
        self.sms.assert_not_called()

    def test_see_list_pick_and_none(self):
        self._window()
        (self.match | self.match2).action_approve()
        self.Match._cron_send_job_alerts()
        Session = self.env['chat2work.wa.session']
        self.assertTrue(Session.wa_handle(tap('27820006001', 'c2w:jobs'), {}))
        rows = self.sent[-1]['interactive']['action']['sections'][0]['rows']
        self.assertEqual({r['title'] for r in rows[:2]}, {'Packer', 'Call centre agent'})
        self.assertEqual(rows[-1]['id'], 'c2w:job:none')
        Session.wa_handle(tap('27820006001', 'c2w:job:%d' % self.match.id), {})
        self.assertEqual(self.match.response, 'interested')
        callback = self.env['chat2work.callback.request'].search([('candidate_id', '=', self.cand.id)])
        self.assertIn('Call centre agent', callback.notes)
        self.assertIn("you're interested in Call centre agent", self.sent[-1]['interactive']['body']['text'])
        Session.wa_handle(tap('27820006001', 'c2w:job:none'), {})
        self.assertEqual(self.match2.response, 'not_interested')
        self.assertEqual(self.match.response, 'interested')

    def test_someone_elses_match_is_refused(self):
        other = self.env['chat2work.candidate'].create({'name': 'Other', 'phone': '+27820006002'})
        Session = self.env['chat2work.wa.session']
        Session.wa_handle(tap('27820006002', 'c2w:job:%d' % self.match.id), {})
        self.assertIn("isn't available", self.sent[-1]['text']['body'])
        self.assertFalse(self.match.response)
        self.assertTrue(other)

    def test_welcome_back_menu_offers_job_matches(self):
        self._window()
        self.match.action_approve()
        self.Match._cron_send_job_alerts()
        Session = self.env['chat2work.wa.session']
        text = {'from': '27820006001', 'id': 'wamid.hi', 'type': 'text', 'text': {'body': 'chat2work'}}
        Session.wa_handle(text, {})
        rows = self.sent[-1]['interactive']['action']['sections'][0]['rows']
        self.assertIn('My job matches', [r['title'] for r in rows])
        Session.wa_handle(tap('27820006001', 'c2w:3'), {})
        self.assertEqual(self.sent[-1]['interactive']['type'], 'list')
        self.assertEqual(self.sent[-1]['interactive']['action']['sections'][0]['rows'][0]['title'], 'Call centre agent')
