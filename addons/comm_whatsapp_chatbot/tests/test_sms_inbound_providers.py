# -*- coding: utf-8 -*-
"""Africa's Talking and Connect Mobile inbound SMS webhooks."""

from unittest.mock import patch

from odoo.tests import common, tagged


@tagged('chatbot', 'post_install', '-at_install')
class TestSmsInboundProviders(common.HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.sms.account']
        cls.at_account = Account.create({
            'name': 'AT In', 'provider': 'africastalking', 'sender_id': '40404',
            'username': 'sandbox', 'api_key': 'k',
        })
        cls.cm_account = Account.create({
            'name': 'CM In', 'provider': 'connect_mobile', 'sender_id': '27820000003', 'api_key': 'k',
        })

    def _patch_inbound(self):
        return patch.object(type(self.env['whatsapp.chatbot.message']), 'process_incoming_sms_message')

    def test_africastalking_inbound(self):
        with self._patch_inbound() as inbound:
            response = self.url_open(
                f'/sms/africastalking/inbound?token={self.at_account.webhook_token}',
                data={'from': '+27820000099', 'to': '40404', 'text': 'JOIN', 'id': 'at-mo-1',
                      'date': '2026-10-28 10:00:00', 'linkId': 'l1'})
        self.assertEqual(response.status_code, 200)
        inbound.assert_called_once_with(from_number='+27820000099', message_text='JOIN',
                                        sms_message_id='at-mo-1', to_number='40404')

    def test_connect_mobile_inbound_uses_account_sender(self):
        with self._patch_inbound() as inbound:
            response = self.url_open(
                f'/sms/connectmobile/inbound?token={self.cm_account.webhook_token}'
                '&oa=27820000099&da=%2B27820000003&ud=JOIN&sms_id=cm-mo-1')
        self.assertEqual(response.status_code, 200)
        inbound.assert_called_once_with(from_number='27820000099', message_text='JOIN',
                                        sms_message_id='cm-mo-1', to_number='27820000003')

    def test_inbound_rejects_bad_token(self):
        with self._patch_inbound() as inbound:
            self.assertEqual(self.url_open('/sms/africastalking/inbound',
                                           data={'from': '+27820000099', 'text': 'x'}).status_code, 403)
            self.assertEqual(self.url_open(
                f'/sms/connectmobile/inbound?token={self.at_account.webhook_token}&oa=1&ud=x').status_code, 403)
        inbound.assert_not_called()
