# -*- coding: utf-8 -*-
"""Chat2Work activity lands on the candidate's UCX conversation, and only
once there's a candidate (after consent)."""

from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.chat2work.tests.test_chat2work_ussd import make_id, years_ago
from odoo.addons.chat2work.tests.test_chat2work_whatsapp import tap, text

CODE = '*384*9999#'
WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workUcx(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Ussd = cls.env['chat2work.ussd.session']
        cls.Wa = cls.env['chat2work.wa.session']
        cls.Candidate = cls.env['chat2work.candidate']
        cls.Interaction = cls.env['comm.interaction']
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('chat2work.ussd_age_min', '18')
        ICP.set_param('chat2work.ussd_age_max', '34')
        ICP.set_param('chat2work.public_base_url', 'https://c2w.example')
        ICP.set_param('chat2work.wa_phone_number_id', '')
        ICP.set_param('chat2work.wa_welcome_image_url', 'none')
        ICP.set_param('chat2work.wa_triggers', 'chat2work,ispani')
        Channel = cls.env['comm.channel'].sudo()
        if not Channel.search([('code', '=', 'web')]):  # comes from comm_chatbot_web on a real install
            Channel.create({'name': 'Web', 'code': 'web', 'adapter_key': 'web'})
        cls._sid = 0

    def setUp(self):
        super().setUp()
        self.wa_count = 0
        patch(WA, autospec=True, side_effect=self._fake_send).start()
        patch('odoo.addons.chat2work.models.chat2work_cv._send_sms', return_value=True).start()
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)

    def _fake_send(self, _self, recipient, content, account=None, log_body='', log_type='interactive'):
        self.wa_count += 1
        return {'success': True, 'message_id': 'wamid.ucx%d' % self.wa_count}

    def dial(self, phone, *inputs):
        type(self)._sid += 1
        sid = 'ATUid_ucx_%d' % self._sid
        crumbs = []
        self.Ussd.ussd_handle(sid, CODE, phone, '', '')
        for inp in inputs:
            crumbs.append(inp)
            self.Ussd.ussd_handle(sid, CODE, phone, '*'.join(crumbs), inp)

    def logged(self, phone):
        cand = self.Candidate.search([('phone', '=', phone)])
        return cand, self.Interaction.search([('conversation_id.partner_id', '=', cand.partner_id.id)], order='id') \
            if cand.partner_id else self.Interaction.browse()

    def test_ussd_profile_is_one_timeline_entry(self):
        id_no = make_id(years_ago(25))
        self.dial('+27820100001', '1', '1', '1', id_no, '1', '1')
        cand, items = self.logged('+27820100001')
        self.assertTrue(cand.partner_id, 'contact created for the new candidate')
        self.assertEqual(cand.partner_id.mobile, '+27820100001')
        self.assertEqual(len(items), 1)
        self.assertEqual(items.channel_id.code, 'ussd')
        self.assertEqual(items.direction, 'inbound')
        self.assertEqual(items.raw_body,
                         'USSD session: Create Profile › Terms: I agree › WhatsApp: Yes › [ID number] › '
                         'Status: Unemployed › Looking for work: Yes\n'
                         'Result: Profile created! We will contact you soon via WhatsApp/SMS.')
        self.assertNotIn(id_no, items.raw_body)
        self.assertEqual(items.conversation_id.campaign_id, 'chat2work')

    def test_cv_link_sms_is_logged(self):
        self.dial('+27820100002', '1', '1', '2', make_id(years_ago(22)), '1', '1')
        cand, _items = self.logged('+27820100002')
        cand._c2w_send_cv_link_now()                      # no WhatsApp → SMS
        _cand, items = self.logged('+27820100002')
        sms = items.filtered(lambda i: i.channel_id.code == 'sms')
        self.assertEqual(len(sms), 1)
        self.assertEqual(sms.direction, 'outbound')
        self.assertIn(cand._c2w_cv_url(), sms.raw_body)
        self.assertEqual(len(items.conversation_id), 1, 'same thread as the USSD session')

    def test_no_consent_logs_nothing(self):
        before_partners = self.env['res.partner'].search_count([])
        before = self.Interaction.search_count([])
        self.dial('+27820100003', '1', '2')               # Create Profile, I do not agree
        self.dial('+27820100003', '2')                    # Request Callback without a profile
        self.dial('+27820100003', '1')                    # abandoned (gateway hang-up)
        self.Ussd.ussd_session_closed('ATUid_ucx_%d' % self._sid)
        self.assertEqual(self.Interaction.search_count([]), before)
        self.assertEqual(self.env['res.partner'].search_count([]), before_partners)

    def test_returning_caller_reuses_contact_and_thread(self):
        partner = self.env['res.partner'].create({'name': 'Thandi Mokoena', 'mobile': '0820100004'})
        self.dial('+27820100004', '1', '1', '2', make_id(years_ago(30)), '2', '2')
        cand, items = self.logged('+27820100004')
        self.assertEqual(cand.partner_id, partner)
        conversation = items.conversation_id
        self.dial('+27820100004', '1', '1', '1')          # Update Status: Unemployed, looking
        _cand, items = self.logged('+27820100004')
        self.assertEqual(len(items), 2)
        self.assertEqual(items.conversation_id, conversation)
        self.assertIn('Update Status › Status: Unemployed › Looking for work: Yes', items[-1].raw_body)

    def test_whatsapp_chat_logged_message_by_message(self):
        wa = '27820100005'
        id_no = make_id(years_ago(24))
        for msg in (text(wa, 'Hi Ispani'), tap(wa, '1'), tap(wa, '1'), text(wa, id_no), tap(wa, '1'), tap(wa, '1')):
            self.Wa.wa_handle(msg, {})
        cand, items = self.logged('+' + wa)
        self.assertTrue(items)
        self.assertEqual(set(items.mapped('channel_id.code')), {'whatsapp'})
        inbound = items.filtered(lambda i: i.direction == 'inbound').mapped('raw_body')
        self.assertEqual(inbound, ['Hi Ispani', 'Create Profile', 'Terms: I agree', '[ID number]',
                                   'Status: Unemployed', 'Looking for work: Yes'])
        self.assertFalse([b for b in items.mapped('raw_body') if id_no in b])
        self.assertIn('Add my CV: ' + cand._c2w_cv_url(), items.mapped('raw_body'))

    def test_whatsapp_status_updates_timeline(self):
        cand = self.Candidate.create({'name': 'Sipho', 'phone': '+27820100006', 'consent_at': fields.Datetime.now()})
        msg = self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.status1', 'is_incoming': False, 'message_type': 'template',
            'message_timestamp': fields.Datetime.now(),
        })
        cand._c2w_log_event('whatsapp', 'outbound', 'CV link', wa_message_id='wamid.status1')
        item = self.logged('+27820100006')[1]
        self.assertEqual((item.source_model, item.source_id, item.status), ('whatsapp.message', msg.id, 'sent'))
        msg.write({'message_status': 'read'})
        self.assertEqual(item.status, 'read')
        msg.write({'message_status': 'delivered'})     # late webhook doesn't move it back
        self.assertEqual(item.status, 'read')

    def test_cv_page_actions_logged(self):
        cand = self.Candidate.create({'name': 'Lerato', 'phone': '+27820100007', 'consent_at': fields.Datetime.now()})
        cand._c2w_store_cv_file('CV upload.pdf', b'%PDF-1.4', 'application/pdf', 'uploaded')
        cand._c2w_request_cv_help()
        items = self.logged('+27820100007')[1]
        self.assertEqual([i.channel_id.code for i in items], ['web', 'web'])
        self.assertEqual(items.mapped('raw_body'), [
            'Uploaded a CV on the CV page: CV upload.pdf',
            'Asked for help creating a CV (CV page). Callback request logged.'])

    def test_simulator_logs_nothing(self):
        self.Candidate.create({'name': 'Ayanda', 'phone': '+27820100008', 'consent_at': fields.Datetime.now()})
        before = self.Interaction.search_count([])
        self.Ussd.with_context(chat2work_ussd_simulation=True).ussd_handle('ATUid_sim', CODE, '+27820100008', '', '')
        self.Ussd.with_context(chat2work_ussd_simulation=True).ussd_session_closed('ATUid_sim')
        self.assertEqual(self.Interaction.search_count([]), before)
