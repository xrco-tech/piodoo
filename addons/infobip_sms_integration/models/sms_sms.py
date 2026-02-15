# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import threading
from uuid import uuid4

from werkzeug.urls import url_join

from odoo import api, fields, models, tools, _
from odoo.addons.sms.tools.sms_api import SmsApi
from odoo.exceptions import UserError, ValidationError
import requests

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    # infobip_status_group = fields.Char("InfoBip Status Group")
    # infobip_status_name = fields.Char("InfoBip Status Name")
    # infobip_status_description = fields.Char("InfoBip Status Description")

    @staticmethod
    def get_mapped_infobip_state(status):
        """
        Expected input:
        "status": {
            "description": "Message sent to next instance",
            "groupId": 1,
            "groupName": "PENDING",
            "id": 26,
            "name": "PENDING_ACCEPTED"
        }

        Output:
        - if status is valid, return state matching Odoo sms state
        - if status is invalid, return 'error' state
        """
        _logger.info(f'status: {status}')
        if type(status) != dict:
            _logger.error("Invalid 'status' object from InfoBip response payload")
            return 'error'
        
        status_group = status.get('groupName')

        if not status_group:
            _logger.error("Invalid status group from InfoBip response payload")
            return 'error'

        if status_group == 'PENDING':
            return 'success'
        elif status_group == 'DELIVERED':
            return 'delivered'
        elif status_group in ['UNDELIVERABLE', 'EXPIRED', 'REJECTED', None]:
            return 'error'
        
    @staticmethod
    def get_mapped_infobip_failure_type(error):
        """
        Expected input:
        "error": {
            "id": 0,
            "name": "NO_ERROR",
            "description": "No Error",
            "groupId": 0,
            "groupName": "OK",
            "permanent": False
        }

        Output:
        - if error not 'OK'/'NO_ERROR', return error matching Odoo sms failure type
        - if error is OK'/'NO_ERROR', return False
        """
        _logger.info(f'error: {error}')
        if type(error) != dict:
            _logger.error("Invalid 'error' object from InfoBip response payload")
            return 'error'
        
        error_name = error.get('name')

        if not error_name:
            _logger.error("Invalid error name from InfoBip response payload")
            return 'error'

        if error_name in ['OK', None]:
            return False
        elif error_name in ['EC_EXCEEDED_THE_TIME_LIMIT_OF_SMS_DEMO', 'EC_EXCEEDED_THE_MAX_NUMBER', 'EC_MONTHLY_LIMIT_REACHED', 'EC_NOT_ENOUGH_CREDITS']:
            return 'insufficient_credit'
        elif error_name in ['EC_ACC_NOT_PROVISIONED_TO_SMS_DEMO_SC', 'EC_ACCOUNT_ACCESS_DENIED']:
            return 'unregistered'
        elif error_name in ['EC_UNIDENTIFIED_SUBSCRIBER', 'EC_INVALID_REQUEST_DESTINATION', 'EC_INVALID_PDU_FORMAT', 'EC_INVALID_DESTINATION_ADDRESS']:
            return 'wrong_number_format'
        elif error_name:
            return 'server_error'
        
    def _send_using_infobip_api(self, messages, raise_exception=False):
        _logger.info(f'messages: {messages}')
        infobip_api_base_url = self.env['ir.config_parameter'].get_param('infobip.base_url', default=False)
        infobip_api_key = self.env['ir.config_parameter'].get_param('infobip.api_key', default=False)
        if not infobip_api_base_url or not infobip_api_key:
            if raise_exception:
                raise ValidationError("Invalid InfoBip API Credentials Set")
            
            result = [
                {
                    "uuid": message.get('destinations', [{}])[0].get('messageId', False), 
                    "state":  "unregistered"
                } for message in messages
            ]
            _logger.info(f'result: {result}')
            return result

        payload = {
            "messages": messages
        }
        headers = {
            'Authorization': f'App {infobip_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.post(
            f'https://{infobip_api_base_url}/sms/2/text/advanced',
            json=payload,
            headers=headers
        )
        _logger.info(f'response: {response}')

        result = []
        if response.status_code == 200:
            resp = response.json()
            resp_messages = resp.get('messages', [])
            _logger.info(f'resp_messages: {resp_messages}')
            result = [
                {
                    "uuid": message.get('messageId', False),
                    "state":  self.get_mapped_infobip_state(message.get('status', {})) if self.get_mapped_infobip_state(message.get('status', {})) != 'error' else self.get_mapped_infobip_failure_type(message.get('error', {})),
                } for message in resp_messages
            ]
            _logger.info(f'result: {result}')
            return result
        else:
            result = [
                {
                    "uuid": message.get('destinations', [{}])[0].get('messageId', False), 
                    "state":  "server_error"
                } for message in messages
            ]
            _logger.info(f'result: {result}')
            return result

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """Send SMS after checking the number (presence and formatting)."""
        # Override default send method if InfoBip explecitly selected
        check_use_infobib_api = self.env['ir.config_parameter'].get_param('sms.use_infobip_api', default=False)
        if check_use_infobib_api:
            default_from_number = self.env['ir.config_parameter'].get_param('infobip.default_from_number', default=False)
            if not default_from_number:
                if raise_exception:
                    raise ValidationError("Default From (Sender) Number Not Set For InfoBip API")

            local_base_url = self[0].get_base_url()
            # Enforce the use of SSL-protected delivery URLs
            if local_base_url.startswith('http://'):
                local_base_url = local_base_url.replace('http://', 'https://')
            delivery_reports_url = url_join(local_base_url, '/sms/infobip/status')
            messages = [{
                'text': body,
                'from': default_from_number,
                'notifyUrl': delivery_reports_url,
                "destinations": [{"to": sms.number, 'messageId': sms.uuid}  for sms in body_sms_records],
            } for body, body_sms_records in self.grouped('body').items()]

            try:
                results = self._send_using_infobip_api(messages,raise_exception=raise_exception)
            except Exception as e:
                _logger.info('Sent batch %s SMS: %s: failed with exception %s', len(self.ids), self.ids, e)
                if raise_exception:
                    raise
                results = [{'uuid': sms.uuid, 'state': 'server_error'} for sms in self]
            else:
                _logger.info('Send batch %s SMS: %s: gave %s', len(self.ids), self.ids, results)

            results_uuids = [result['uuid'] for result in results]
            all_sms_sudo = self.env['sms.sms'].sudo().search([('uuid', 'in', results_uuids)]).with_context(sms_skip_msg_notification=True)

            for iap_state, results_group in tools.groupby(results, key=lambda result: result['state']):
                _logger.info(f'iap_state: {iap_state}, results_group: {results_group}')
                sms_sudo = all_sms_sudo.filtered(lambda s: s.uuid in {result['uuid'] for result in results_group})
                if success_state := self.IAP_TO_SMS_STATE_SUCCESS.get(iap_state):
                    sms_sudo.sms_tracker_id._action_update_from_sms_state(success_state)
                    sms_sudo.write({'state': success_state, 'failure_type': False})
                else:
                    failure_type = self.IAP_TO_SMS_FAILURE_TYPE.get(iap_state, 'unknown')
                    if failure_type != 'unknown':
                        sms_sudo.sms_tracker_id._action_update_from_sms_state('error', failure_type=failure_type)
                    else:
                        sms_sudo.sms_tracker_id._action_update_from_provider_error(iap_state)
                    sms_sudo.write({'state': 'error', 'failure_type': failure_type})

            all_sms_sudo.mail_message_id._notify_message_notification_update()
