# -*- coding: utf-8 -*-
"""A call permission request WhatsApp couldn't deliver is not left "waiting for reply"."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import common, new_test_user, tagged

SEND = 'odoo.addons.bus.models.bus.ImBus._sendone'


def failed(message_id):
    return {'id': message_id, 'status': 'failed', 'timestamp': '1762500000', 'recipient_id': '27820000002',
            'errors': [{'code': 131042, 'title': 'Business eligibility payment issue'}]}


@tagged('post_install', '-at_install')
class TestCallPermissionDelivery(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.agent = new_test_user(self.env, 'wa_perm_agent', groups='base.group_user')
        self.partner = self.env['res.partner'].create({'name': 'Zanele Dube'})
        self.permission = self.env['whatsapp.call.permission'].create({
            'phone': '27820000002', 'phone_number_id': '1234567890', 'partner_id': self.partner.id,
            'state': 'pending', 'requested_at': fields.Datetime.now(), 'requested_by_id': self.agent.id,
            'request_message_id': 'wamid.perm1'})

    def test_failed_request_is_flagged_and_the_agent_is_told(self):
        with patch(SEND) as sendone:
            self.env['whatsapp.message']._apply_status_update(failed('wamid.perm1'))
        self.assertEqual(self.permission.state, 'failed')
        self.assertIn('unpaid charges', self.permission.fail_reason)
        told = [c.args for c in sendone.call_args_list if c.args[1] == 'whatsapp_call_permission']
        self.assertEqual(len(told), 1)
        self.assertEqual(told[0][0], self.agent.partner_id)
        self.assertEqual(told[0][2]['state'], 'failed')
        self.assertIn('was not delivered', told[0][2]['message'])
        self.assertIn('unpaid charges', told[0][2]['message'])
        self.assertEqual(self.permission.current_state, 'failed')
        self.assertIn('unpaid charges', self.permission._describe('Zanele'))
        self.assertTrue(self.partner.message_ids.filtered(lambda m: 'was not delivered' in (m.body or '')))

    def test_other_failures_and_answered_requests_are_left_alone(self):
        self.env['whatsapp.message']._apply_status_update(failed('wamid.someone_else'))
        self.assertEqual(self.permission.state, 'pending')
        self.permission.state = 'granted'
        self.env['whatsapp.message']._apply_status_update(failed('wamid.perm1'))
        self.assertEqual(self.permission.state, 'granted')
