# -*- coding: utf-8 -*-
"""Provider dispatch, Africa's Talking / Connect Mobile senders and
delivery-report webhooks."""

from unittest.mock import MagicMock, patch

from odoo.tests import common, tagged

PROVIDERS = 'odoo.addons.comm_sms.models.sms_sms_providers.requests.post'
INFOBIP = 'odoo.addons.comm_sms.models.sms_sms.requests.post'


def _response(status_code, json_data=None, headers=None, text=''):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.headers = headers or {}
    response.text = text
    return response


def _at_response(*recipients):
    return _response(201, {'SMSMessageData': {'Message': 'Sent', 'Recipients': list(recipients)}})


class SmsProviderCase(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sms.use_infobip_api', False)
        Account = cls.env['comm.sms.account']
        cls.at_account = Account.create({
            'name': 'AT', 'provider': 'africastalking', 'sender_id': 'TESTAT',
            'username': 'sandbox', 'api_key': 'at-key', 'use_sandbox': True, 'sequence': 1,
        })
        cls.cm_account = Account.create({
            'name': 'CM', 'provider': 'connect_mobile', 'sender_id': '27820000001',
            'api_key': 'cm-token', 'sequence': 2,
        })
        cls.ib_account = Account.create({
            'name': 'IB', 'provider': 'infobip', 'sender_id': 'TESTIB',
            'base_url': 'example.api.infobip.com', 'api_key': 'ib-key', 'sequence': 3,
        })

    def _sms(self, number='+27820000099', body='Hello', account=None):
        vals = {'number': number, 'body': body}
        if account:
            vals['account_id'] = account.id
        return self.env['sms.sms'].create(vals)


@tagged('comm_sms', 'post_install', '-at_install')
class TestSmsDispatch(SmsProviderCase):

    def test_africastalking_send(self):
        sms = self._sms(account=self.at_account)
        with patch(PROVIDERS, return_value=_at_response(
                {'statusCode': 101, 'number': '+27820000099', 'status': 'Success', 'messageId': 'ATXid_1'})) as post:
            sms._send(raise_exception=True)
        url, = post.call_args.args
        self.assertEqual(url, 'https://api.sandbox.africastalking.com/version1/messaging/bulk')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['username'], 'sandbox')
        self.assertEqual(payload['senderId'], 'TESTAT')
        self.assertEqual(payload['phoneNumbers'], ['+27820000099'])
        self.assertEqual(post.call_args.kwargs['headers']['apiKey'], 'at-key')
        self.assertEqual(sms.state, 'pending')
        self.assertEqual(sms.provider_message_id, 'ATXid_1')

    def test_africastalking_recipient_error(self):
        sms = self._sms(account=self.at_account)
        with patch(PROVIDERS, return_value=_at_response(
                {'statusCode': 405, 'number': '+27820000099', 'status': 'InsufficientBalance', 'messageId': 'None'})):
            sms._send()
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_credit')
        self.assertFalse(sms.provider_message_id)

    def test_africastalking_missing_recipient_is_error(self):
        sms_a = self._sms(number='+27820000011', account=self.at_account)
        sms_b = self._sms(number='+27820000012', account=self.at_account)
        with patch(PROVIDERS, return_value=_at_response(
                {'statusCode': 101, 'number': '+27820000011', 'messageId': 'ATXid_a'})):
            (sms_a | sms_b)._send()
        self.assertEqual(sms_a.state, 'pending')
        self.assertEqual(sms_b.state, 'error')

    def test_africastalking_missing_credentials(self):
        self.at_account.username = False
        sms = self._sms(account=self.at_account)
        with patch(PROVIDERS) as post:
            sms._send()
        post.assert_not_called()
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_acc')

    def test_connect_mobile_send(self):
        sms = self._sms(account=self.cm_account)
        with patch(PROVIDERS, return_value=_response(202, headers={'X-SMS-ID': 'cm-42'})) as post:
            sms._send(raise_exception=True)
        url, = post.call_args.args
        self.assertEqual(url, 'https://sms.connect-mobile.co.za/submit/single/')
        self.assertEqual(post.call_args.kwargs['data'], {'da': '+27820000099', 'ud': 'Hello', 'id': sms.uuid})
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer cm-token')
        self.assertEqual(sms.state, 'pending')
        self.assertEqual(sms.provider_message_id, 'cm-42')

    def test_connect_mobile_auth_failure(self):
        sms = self._sms(account=self.cm_account)
        with patch(PROVIDERS, return_value=_response(401, text='Unauthorized')):
            sms._send()
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_acc')

    def test_mixed_batch_goes_to_each_provider(self):
        sms_at = self._sms(account=self.at_account)
        sms_ib = self._sms(account=self.ib_account)
        ib_response = _response(200, {'messages': [
            {'messageId': sms_ib.uuid, 'status': {'groupName': 'PENDING'}}]})
        at_response = _at_response({'statusCode': 101, 'number': '+27820000099', 'messageId': 'ATXid_2'})
        calls = {}

        def fake_post(url, **kwargs):
            calls[url] = kwargs
            return at_response if 'africastalking' in url else ib_response

        # Both modules share the one `requests` module, so a single patch serves both.
        with patch(INFOBIP, side_effect=fake_post):
            (sms_at | sms_ib)._send()
        self.assertEqual(len(calls), 2)
        ib_url = next(url for url in calls if 'infobip' in url)
        self.assertEqual(ib_url, 'https://example.api.infobip.com/sms/2/text/advanced')
        self.assertIn('token=', calls[ib_url]['json']['messages'][0]['notifyUrl'])
        self.assertEqual(sms_at.state, 'pending')
        self.assertEqual(sms_ib.state, 'pending')

    def test_no_account_switch_off_uses_standard_provider(self):
        sms = self._sms()
        with patch.object(type(self.env['sms.sms']), '_send_with_api') as standard, \
                patch(PROVIDERS) as post:
            sms._send()
        standard.assert_called_once()
        post.assert_not_called()
        self.assertFalse(sms.account_id)

    def test_no_account_switch_on_uses_default_account(self):
        self.env['ir.config_parameter'].sudo().set_param('sms.use_infobip_api', True)
        self.cm_account.is_default = True
        sms = self._sms()
        with patch(PROVIDERS, return_value=_response(202)) as post:
            sms._send()
        post.assert_called_once()
        self.assertEqual(sms.account_id, self.cm_account)
        self.assertEqual(sms.state, 'pending')


@tagged('comm_sms', 'post_install', '-at_install')
class TestSmsAccountWebhooks(SmsProviderCase):

    def test_each_account_has_own_token(self):
        self.assertTrue(self.at_account.webhook_token)
        self.assertNotEqual(self.at_account.webhook_token, self.cm_account.webhook_token)

    def test_webhook_urls(self):
        self.assertTrue(self.at_account.dlr_webhook_url.startswith('https://'))
        self.assertTrue(self.at_account.dlr_webhook_url.endswith(
            f'/sms/africastalking/status?token={self.at_account.webhook_token}'))
        self.assertIn('/sms/connectmobile/inbound?token=', self.cm_account.inbound_webhook_url)

    def test_regenerate_token(self):
        old = self.at_account.webhook_token
        self.at_account.action_regenerate_webhook_token()
        self.assertNotEqual(self.at_account.webhook_token, old)

    def test_find_for_webhook_token_is_per_provider(self):
        Account = self.env['comm.sms.account']
        self.assertEqual(Account.find_for_webhook_token('africastalking', self.at_account.webhook_token),
                         self.at_account)
        self.assertFalse(Account.find_for_webhook_token('connect_mobile', self.at_account.webhook_token))
        self.assertFalse(Account.find_for_webhook_token('africastalking', ''))


@tagged('comm_sms', 'post_install', '-at_install')
class TestDeliveryReportWebhooks(common.HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.sms.account']
        cls.at_account = Account.create({
            'name': 'AT DLR', 'provider': 'africastalking', 'sender_id': 'DLRAT',
            'username': 'sandbox', 'api_key': 'k',
        })
        cls.cm_account = Account.create({
            'name': 'CM DLR', 'provider': 'connect_mobile', 'sender_id': '27820000002', 'api_key': 'k',
        })
        cls.ib_account = Account.create({
            'name': 'IB DLR', 'provider': 'infobip', 'sender_id': 'DLRIB',
        })

    def _sms(self, account, **vals):
        return self.env['sms.sms'].create({
            'number': '+27820000099', 'body': 'Hi', 'account_id': account.id, 'state': 'pending', **vals})

    def test_africastalking_dlr_delivered(self):
        sms = self._sms(self.at_account, provider_message_id='ATXid_dlr')
        response = self.url_open(
            f'/sms/africastalking/status?token={self.at_account.webhook_token}',
            data={'id': 'ATXid_dlr', 'status': 'Success', 'phoneNumber': '+27820000099'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sms.state, 'sent')

    def test_africastalking_dlr_failed(self):
        sms = self._sms(self.at_account, provider_message_id='ATXid_fail')
        self.url_open(
            f'/sms/africastalking/status?token={self.at_account.webhook_token}',
            data={'id': 'ATXid_fail', 'status': 'Failed', 'failureReason': 'InsufficientCredit'})
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_credit')

    def test_africastalking_dlr_rejects_bad_token(self):
        sms = self._sms(self.at_account, provider_message_id='ATXid_tok')
        for url in ('/sms/africastalking/status', '/sms/africastalking/status?token=nope',
                    f'/sms/africastalking/status?token={self.cm_account.webhook_token}'):
            response = self.url_open(url, data={'id': 'ATXid_tok', 'status': 'Success'})
            self.assertEqual(response.status_code, 403, url)
        self.assertEqual(sms.state, 'pending')

    def test_connect_mobile_dlr_by_userid(self):
        sms = self._sms(self.cm_account)
        response = self.url_open(
            f'/sms/connectmobile/dlr?token={self.cm_account.webhook_token}'
            f'&status=DELIVERED&userid={sms.uuid}&smsid=cm-1&da=27820000099')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sms.state, 'sent')

    def test_connect_mobile_dlr_late_pending_keeps_delivery(self):
        sms = self._sms(self.cm_account, state='sent')
        self.url_open(f'/sms/connectmobile/dlr?token={self.cm_account.webhook_token}'
                      f'&status=PENDING&userid={sms.uuid}')
        self.assertEqual(sms.state, 'sent')

    def test_connect_mobile_dlr_rejects_missing_token(self):
        sms = self._sms(self.cm_account)
        response = self.url_open(f'/sms/connectmobile/dlr?status=DELIVERED&userid={sms.uuid}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(sms.state, 'pending')

    def test_infobip_dlr_pending_and_delivered(self):
        sms = self._sms(self.ib_account, state='process')
        url = f'/sms/infobip/status?token={self.ib_account.webhook_token}'
        headers = {'Content-Type': 'application/json'}
        self.url_open(url, data=f'{{"results": [{{"messageId": "{sms.uuid}", '
                                f'"status": {{"groupName": "PENDING"}}}}]}}', headers=headers)
        self.assertEqual(sms.state, 'pending')
        self.url_open(url, data=f'{{"results": [{{"messageId": "{sms.uuid}", '
                                f'"status": {{"groupName": "DELIVERED"}}}}]}}', headers=headers)
        self.assertEqual(sms.state, 'sent')

    def test_infobip_dlr_rejected_maps_failure(self):
        sms = self._sms(self.ib_account)
        self.url_open('/sms/infobip/status', headers={'Content-Type': 'application/json'},
                      data=f'{{"results": [{{"messageId": "{sms.uuid}", "status": {{"groupName": "REJECTED"}}, '
                           f'"error": {{"name": "EC_NOT_ENOUGH_CREDITS"}}}}]}}')
        self.assertEqual(sms.state, 'error')
        self.assertEqual(sms.failure_type, 'sms_credit')

    def test_infobip_dlr_rejects_wrong_token(self):
        sms = self._sms(self.ib_account)
        response = self.url_open('/sms/infobip/status?token=nope', headers={'Content-Type': 'application/json'},
                                 data=f'{{"results": [{{"messageId": "{sms.uuid}", "status": {{"groupName": "DELIVERED"}}}}]}}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(sms.state, 'pending')
