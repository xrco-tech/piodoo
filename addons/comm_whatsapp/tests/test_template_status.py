# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock

from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestTemplateStatusSync(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.tpl = self.env['whatsapp.template'].create({
            'name': 'status_sync_test', 'language': 'en', 'category': 'MARKETING',
            'body': 'Hello', 'template_id_meta': '987654',
        })
        self.assertEqual(self.tpl.status, 'PENDING')

    def test_webhook_approves_by_meta_id(self):
        T = self.env['whatsapp.template']
        self.assertTrue(T._handle_status_webhook({
            'event': 'APPROVED', 'message_template_id': 987654,
            'message_template_name': 'status_sync_test', 'message_template_language': 'en',
            'reason': 'NONE'}))
        self.assertEqual(self.tpl.status, 'APPROVED')
        self.assertFalse(self.tpl.rejection_reason)

    def test_webhook_rejects_by_name_with_reason(self):
        self.tpl.template_id_meta = False
        self.env['whatsapp.template']._handle_status_webhook({
            'event': 'REJECTED', 'message_template_name': 'status_sync_test',
            'message_template_language': 'en', 'reason': 'INVALID_FORMAT'})
        self.assertEqual(self.tpl.status, 'REJECTED')
        self.assertEqual(self.tpl.rejection_reason, 'INVALID_FORMAT')

    def test_untracked_event_and_unknown_template_change_nothing(self):
        T = self.env['whatsapp.template']
        self.assertFalse(T._handle_status_webhook({'event': 'FLAGGED', 'message_template_id': 987654}))
        self.assertFalse(T._handle_status_webhook({'event': 'APPROVED', 'message_template_id': 1}))
        self.assertEqual(self.tpl.status, 'PENDING')

    def test_cron_asks_meta_about_pending(self):
        self.env['ir.config_parameter'].sudo().set_param('comm_whatsapp.access_token', 'test-token')
        resp = MagicMock(status_code=200)
        resp.json.return_value = {'status': 'APPROVED', 'id': '987654'}
        with patch('odoo.addons.comm_whatsapp.models.whatsapp_template.requests.get',
                   return_value=resp) as get:
            self.env['whatsapp.template']._cron_sync_pending_status()
        self.assertTrue(any('987654' in c.args[0] for c in get.call_args_list))
        self.assertEqual(self.tpl.status, 'APPROVED')
