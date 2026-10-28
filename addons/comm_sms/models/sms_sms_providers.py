# -*- coding: utf-8 -*-
"""Africa's Talking and Connect Mobile senders for sms.sms.

Each `_send_<provider>(account, raise_exception)` returns the same result
shape as the Infobip sender: ``[{'uuid', 'state', 'provider_message_id'?}]``
with IAP-style states, which sms.sms._apply_send_results writes back.
"""

import logging
import re

import requests

from odoo import models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# https://developers.africastalking.com/docs/sms/sending/bulk — per-recipient statusCode
AFRICASTALKING_SEND_STATES = {
    100: 'success',  # Processed
    101: 'success',  # Sent
    102: 'success',  # Queued
    401: 'server_error',  # RiskHold
    402: 'unregistered',  # InvalidSenderId
    403: 'wrong_number_format',  # InvalidPhoneNumber
    404: 'country_not_supported',  # UnsupportedNumberType
    405: 'insufficient_credit',  # InsufficientBalance
    406: 'server_error',  # UserInBlacklist
    407: 'server_error',  # CouldNotRoute
    409: 'server_error',  # DoNotDisturbRejection
    500: 'server_error',  # InternalServerError
    501: 'server_error',  # GatewayError
    502: 'server_error',  # RejectedByGateway
}

CONNECT_MOBILE_DEFAULT_HOST = 'sms.connect-mobile.co.za'
REQUEST_TIMEOUT = 30


def _msisdn(number, plus=True):
    """International number with only digits (and a leading '+' if `plus`)."""
    digits = re.sub(r'\D', '', number or '')
    return f'+{digits}' if plus and digits else digits


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    # ── Africa's Talking ────────────────────────────────────────────────────

    def _send_africastalking(self, account, raise_exception=False):
        if not (account.username and account.api_key):
            if raise_exception:
                raise ValidationError(_("Africa's Talking username and API key are required on SMS account %s",
                                        account.name))
            return [{'uuid': sms.uuid, 'state': 'unregistered'} for sms in self]

        host = 'api.sandbox.africastalking.com' if account.use_sandbox else 'api.africastalking.com'
        url = f'https://{host}/version1/messaging/bulk'
        headers = {
            'apiKey': account.api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        results = []
        for body, body_sms in self.grouped('body').items():
            payload = {
                'username': account.username,
                'message': body,
                'senderId': account.sender_id,
                'phoneNumbers': [_msisdn(sms.number) for sms in body_sms],
            }
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                _logger.warning("Africa's Talking send failed: %s", e)
                results += [{'uuid': sms.uuid, 'state': 'server_error'} for sms in body_sms]
                continue

            if response.status_code not in (200, 201):
                _logger.warning("Africa's Talking send returned %s: %s", response.status_code, response.text[:500])
                state = 'unregistered' if response.status_code == 401 else 'server_error'
                results += [{'uuid': sms.uuid, 'state': state} for sms in body_sms]
                continue

            recipients = ((response.json() or {}).get('SMSMessageData') or {}).get('Recipients') or []
            # Africa's Talking can't echo our uuid, so match recipients back
            # to SMS by number (in order, for repeated numbers).
            by_number = {}
            for sms in body_sms:
                by_number.setdefault(_msisdn(sms.number, plus=False), []).append(sms)
            for recipient in recipients:
                queue = by_number.get(_msisdn(recipient.get('number'), plus=False))
                if not queue:
                    continue
                sms = queue.pop(0)
                message_id = recipient.get('messageId')
                results.append({
                    'uuid': sms.uuid,
                    'state': AFRICASTALKING_SEND_STATES.get(int(recipient.get('statusCode') or 0), 'server_error'),
                    'provider_message_id': message_id if message_id and message_id != 'None' else False,
                })
            # Numbers the response didn't mention were not sent.
            results += [{'uuid': sms.uuid, 'state': 'server_error'}
                        for queue in by_number.values() for sms in queue]
        return results

    # ── Connect Mobile ──────────────────────────────────────────────────────

    def _send_connect_mobile(self, account, raise_exception=False):
        if not account.api_key:
            if raise_exception:
                raise ValidationError(_("Connect Mobile API token is required on SMS account %s", account.name))
            return [{'uuid': sms.uuid, 'state': 'unregistered'} for sms in self]

        host = (account.base_url or CONNECT_MOBILE_DEFAULT_HOST).strip()
        host = re.sub(r'^https?://', '', host).rstrip('/')
        url = f'https://{host}/submit/single/'
        headers = {'Authorization': f'Bearer {account.api_key}', 'Accept': '*/*'}

        results = []
        # One request per SMS so each carries our uuid as `id`, which Connect
        # Mobile echoes back as `userid` on delivery reports.
        for sms in self:
            data = {'da': _msisdn(sms.number), 'ud': sms.body or '', 'id': sms.uuid}
            try:
                response = requests.post(url, data=data, headers=headers, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                _logger.warning("Connect Mobile send failed for sms %s: %s", sms.id, e)
                results.append({'uuid': sms.uuid, 'state': 'server_error'})
                continue

            if response.status_code == 202:
                results.append({
                    'uuid': sms.uuid,
                    'state': 'success',
                    'provider_message_id': response.headers.get('X-SMS-ID') or False,
                })
            else:
                _logger.warning("Connect Mobile send returned %s for sms %s: %s",
                                response.status_code, sms.id, response.text[:500])
                state = 'unregistered' if response.status_code in (401, 403) else 'server_error'
                results.append({'uuid': sms.uuid, 'state': state})
        return results
