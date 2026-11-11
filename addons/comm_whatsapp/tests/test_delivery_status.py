# -*- coding: utf-8 -*-
"""Meta's delivery statuses land on the message, with the reason when one fails."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import common, tagged

HOOK = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage._wa_delivery_failed'


def failed(message_id, code=131042, title='Business eligibility payment issue', details=None):
    error = {'code': code, 'title': title, 'message': title}
    if details:
        error['error_data'] = {'details': details}
    return {'id': message_id, 'status': 'failed', 'timestamp': '1762500000',
            'recipient_id': '27820000001', 'errors': [error]}


@tagged('post_install', '-at_install')
class TestDeliveryStatus(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.Message = self.env['whatsapp.message']
        self.message = self.Message.create({
            'message_id': 'wamid.status1', 'wa_id': '27820000001', 'is_incoming': False,
            'message_type': 'template', 'status': 'processed', 'message_timestamp': fields.Datetime.now()})

    def test_failure_keeps_metas_reason(self):
        details = 'Message failed to send because your WhatsApp Business account has unsettled payments.'
        self.assertEqual(self.Message._apply_status_update(failed('wamid.status1', details=details)), self.message)
        self.assertEqual(self.message.message_status, 'failed')
        self.assertEqual(self.message.status_error_code, 131042)
        self.assertEqual(self.message.status_error_title, 'Business eligibility payment issue')
        self.assertEqual(self.message.status_error_details, details)
        self.assertIn('unpaid charges', self.message.failure_reason)

    def test_unknown_failure_uses_metas_words(self):
        self.Message._apply_status_update(failed('wamid.status1', code=139999, title='Odd thing', details='Longer why'))
        self.assertEqual(self.message.failure_reason, 'Longer why')
        self.Message._apply_status_update(failed('wamid.status1', code=139998, title='Just a title'))
        self.assertEqual(self.message.failure_reason, 'Just a title')

    def test_delivered_has_no_reason(self):
        self.Message._apply_status_update({'id': 'wamid.status1', 'status': 'delivered', 'timestamp': '1762500000',
                                           'pricing': {'category': 'utility', 'pricing_model': 'PMP'}})
        self.assertEqual(self.message.message_status, 'delivered')
        self.assertEqual(self.message.pricing_category, 'utility')
        self.assertFalse(self.message.failure_reason)

    def test_failure_of_a_message_we_never_logged_still_reaches_the_hook(self):
        with patch(HOOK) as hook:
            self.assertFalse(self.Message._apply_status_update(failed('wamid.unknown')))
            self.Message._apply_status_update({'id': 'wamid.status1', 'status': 'read', 'timestamp': '1762500000'})
        self.assertEqual(hook.call_count, 1)
        message_id, recipient, reason, error = hook.call_args.args
        self.assertEqual((message_id, recipient, error['code']), ('wamid.unknown', '27820000001', 131042))
        self.assertIn('unpaid charges', reason)

    def test_a_broken_follow_up_does_not_lose_the_status(self):
        with patch(HOOK, side_effect=ValueError('boom')), \
                self.assertLogs('odoo.addons.comm_whatsapp.models.whatsapp_message', 'ERROR'):
            self.Message._apply_status_update(failed('wamid.status1'))
        self.assertEqual(self.message.message_status, 'failed')
