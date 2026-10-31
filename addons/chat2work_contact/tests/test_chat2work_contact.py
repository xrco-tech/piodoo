# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, new_test_user, tagged

MOD = 'odoo.addons.chat2work_contact.wizards.chat2work_message'
SENDER = 'odoo.addons.comm_whatsapp.models.whatsapp_template_send_wizard.WhatsAppTemplateSendWizard.action_send_template'
PAYLOAD = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workContact(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('chat2work.wa_phone_number_id', '')
        self.agent = new_test_user(self.env, login='c2w_contact_agent', groups='chat2work.group_agent')
        self.cand = self.env['chat2work.candidate'].create({
            'name': 'Thandeka Mokoena', 'phone': '+27820007001', 'whatsapp_opt_in': True})
        self.account = self.env['comm.whatsapp.account'].sudo().search([], limit=1) or \
            self.env['comm.whatsapp.account'].sudo().create({'name': 'Test', 'phone_number_id': '123', 'phone_number': '27820000000'})
        self.template = self.env['whatsapp.template'].sudo().create({
            'name': 'job_update', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
            'account_id': self.account.id, 'body': 'Hi {{1}}, about {{2}}.'})

    def _wizard(self, **vals):
        return self.env['chat2work.message'].with_user(self.agent).create(dict({'candidate_id': self.cand.id}, **vals))

    def _inbound(self, hours_ago=1):
        self.env['whatsapp.message'].sudo().create({
            'message_id': 'wamid.c2w%s' % hours_ago, 'wa_id': '27820007001', 'is_incoming': True,
            'message_type': 'text', 'message_timestamp': fields.Datetime.now() - timedelta(hours=hours_ago)})

    def test_call_buttons(self):
        cand = self.cand.with_user(self.agent)
        action = cand.action_c2w_call_whatsapp()
        self.assertEqual(action['tag'], 'comm_whatsapp_calling.dial')
        self.assertEqual(action['params']['to_number'], '+27820007001')
        with self.assertRaises(UserError):
            cand.action_c2w_call_voip()               # no extension
        self.agent.sudo().dialer_sip_ext = '1001'
        cand.invalidate_recordset()
        before = len(cand.message_ids)
        self.assertEqual(cand.action_c2w_call_voip()['params']['number'], '+27820007001')
        self.assertEqual(len(cand.message_ids), before, 'noted only once dialled')
        cand.c2w_note_voip_call()
        self.assertIn('VoIP call attempted', cand.message_ids[0].body)

    def test_no_whatsapp_call_without_whatsapp(self):
        self.cand.whatsapp_opt_in = False
        with self.assertRaises(UserError):
            self.cand.action_c2w_call_whatsapp()

    def test_sms_typed(self):
        with patch(MOD + '._send_sms', return_value=True) as sms:
            self._wizard(channel='sms', body='Hello there').action_send()
        self.assertEqual(sms.call_args.args[1:], ('+27820007001', 'Hello there'))
        self.assertIn('Hello there', self.cand.message_ids[0].body)

    def test_sms_failure_is_shown(self):
        with patch(MOD + '._send_sms', return_value=False), self.assertRaises(UserError):
            self._wizard(channel='sms', body='Hello').action_send()

    def test_sms_template_fills_the_message(self):
        self.cand._c2w_ensure_token()
        wizard = Form(self.env['chat2work.message'].with_context(default_candidate_id=self.cand.id))
        wizard.channel = 'sms'
        wizard.sms_template = str(self.env.ref('chat2work_contact.sms_template_add_cv').id)
        self.assertIn(self.cand.cv_url, wizard.body)

    def test_typed_whatsapp_needs_open_window(self):
        with self.assertRaises(UserError):
            self._wizard(channel='whatsapp', body='Hi').action_send()
        self._inbound(hours_ago=30)
        self.assertFalse(self._wizard().window_open)
        self._inbound(hours_ago=2)
        with patch(PAYLOAD, return_value={'success': True, 'message_id': 'x'}) as send:
            self._wizard(channel='whatsapp', body='Hi').action_send()
        self.assertEqual(send.call_args.args[0], '27820007001')

    def test_template_values_and_preview(self):
        wizard = Form(self.env['chat2work.message'].with_context(default_candidate_id=self.cand.id))
        wizard.channel = 'whatsapp'
        self.assertTrue(wizard.use_template, 'closed window means template only')
        wizard.wa_template = str(self.template.id)
        with wizard.param_ids.edit(1) as line:
            line.value = 'a job'
        self.assertEqual(wizard.preview, 'Hi Thandeka, about a job.')
        record = wizard.save()
        close = {'type': 'ir.actions.act_window_close'}
        with patch(SENDER, return_value=close) as send:
            record.action_send()
        send.assert_called_once()
        self.assertIn('job_update', self.cand.message_ids[0].body)

    def test_template_failure_is_shown(self):
        record = self._wizard(channel='whatsapp', use_template=True, wa_template=str(self.template.id))
        bad = {'type': 'ir.actions.client', 'params': {'message': 'Meta said no'}}
        with patch(SENDER, return_value=bad), self.assertRaisesRegex(UserError, 'Meta said no'):
            record.action_send()

    def test_missing_template_value_blocks_sending(self):
        record = self._wizard(channel='whatsapp', use_template=True, wa_template=str(self.template.id), param_ids=[
            (0, 0, {'number': 1, 'value': 'Thandeka'}), (0, 0, {'number': 2, 'value': ''})])
        with patch(SENDER) as send, self.assertRaises(UserError):
            record.action_send()
        send.assert_not_called()

    def test_template_needing_a_link_value_is_not_offered(self):
        linked = self.env['whatsapp.template'].sudo().create({
            'name': 'linked', 'language': 'en', 'category': 'UTILITY', 'status': 'APPROVED',
            'account_id': self.account.id, 'body': 'Tap below',
            'button_ids': [(0, 0, {'button_type': 'URL', 'text': 'Open', 'url': 'https://x.example/{{1}}'})]})
        options = dict(self.env['chat2work.message'].with_user(self.agent)._wa_template_options())
        self.assertIn(str(self.template.id), options)
        self.assertNotIn(str(linked.id), options)

    def test_whatsapp_blocked_when_not_using_it(self):
        self.cand.whatsapp_opt_in = False
        record = self._wizard(channel='whatsapp', body='Hi')
        with self.assertRaises(UserError):
            record.action_send()
