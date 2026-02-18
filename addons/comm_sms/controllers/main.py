from odoo import http
from odoo.http import request, Response
import json
import logging
import re
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class InfoBipSMSControler(http.Controller):
    @http.route(['/sms/infobip/status'], type="http", auth="public", methods=['POST'], csrf=False)
    def update_sms_status(self, **kwargs):
        try:
            # Check if it's JSON-RPC format or plain JSON
            content_type = request.httprequest.headers.get('Content-Type', '')
            
            if 'application/json' in content_type:
                # Handle plain JSON (webhook)
                raw_data = request.httprequest.data.decode('utf-8')
                json_data = json.loads(raw_data)
                _logger.info(f"Webhook data: {json_data}")
                
                # Process webhook data
                self._process_infobip_webhook(json_data)
                
                return request.make_response(
                    json.dumps({"status": "success"}),
                    headers={'Content-Type': 'application/json'}
                )
            else:
                # TODO: Handle form data or other formats
                _logger.info(f"Form data: {kwargs}")
                return request.make_response(
                    json.dumps({"status": "success"}),
                    headers={'Content-Type': 'application/json'}
                )
                
        except Exception as e:
            _logger.error(f"Error processing request: {e}")
            return request.make_response(
                json.dumps({"error": str(e)}),
                status=500,
                headers={'Content-Type': 'application/json'}
            )
    
    def _process_infobip_webhook(self, data):
        """
        Sample InfoBip Delivery Report (Delivered): {
            "results": [
                {
                    "price": {
                        "pricePerMessage": 0.0,
                        "currency": "USD"
                    },
                    "status": {
                        "id": 5,
                        "groupId": 3,
                        "groupName": "DELIVERED",
                        "name": "DELIVERED_TO_HANDSET",
                        "description": "Message delivered to handset"
                    },
                    "error": {
                        "id": 0,
                        "name": "NO_ERROR",
                        "description": "No Error",
                        "groupId": 0,
                        "groupName": "OK",
                        "permanent": False
                    },
                    "messageId": "992cea8066ed4af0b5e15ab4018af38e",
                    "doneAt": "2025-07-01T22:15:53.473+0000",
                    "smsCount": 1,
                    "sentAt": "2025-07-01T22:15:50.986+0000",
                    "to": "27683264051"
                }
            ]
        }

        Sample InfoBip Delivery Report (Rejected / Insufficient Funds): {
            "results": [
                {
                    "price": {
                        "pricePerMessage": 0.0,
                        "currency": "USD"
                    },
                    "status": {
                        "id": 12,
                        "groupId": 5,
                        "groupName": "REJECTED",
                        "name": "REJECTED_NOT_ENOUGH_CREDITS",
                        "description": "Not enough credits"
                    },
                    "error": {
                        "id": 5754,
                        "name": "EC_NOT_ENOUGH_CREDITS",
                        "description": "Not enough credits",
                        "groupId": 2,
                        "groupName": "USER_ERRORS",
                        "permanent": False
                    },
                    "messageId": "cc9c6a030d314141a9e1a704aabe84ed",
                    "doneAt": "2025-07-01T23:00:54.961+0000",
                    "smsCount": 1,
                    "sentAt": "2025-07-01T23:00:54.958+0000",
                    "to": "27683264051"
                }
            ]
        }
        """
        all_uuids = []
        message_statuses = data.get('results')
        _logger.info(f"message_statuses: {message_statuses}")
        for uuid, iap_status in ((status['messageId'], status['status']['groupName'].lower()) for status in message_statuses):
            _logger.info(f"uuids: {uuid}, iap_status: {iap_status}")
            # self._check_status_values(uuids, iap_status, message_statuses)
            if sms_sudo := request.env['sms.sms'].sudo().search([('uuid', '=', uuid)]):
                _logger.info(f"checking state...")
                if state := request.env['sms.sms'].IAP_TO_SMS_STATE_SUCCESS.get(iap_status):
                    sms_sudo.sms_tracker_id._action_update_from_sms_state(state)
                    sms_sudo.write({'state': state, 'failure_type': False})
                    _logger.info(f"executed _action_update_from_sms_state")
                else:
                    sms_sudo.sms_tracker_id._action_update_from_provider_error(iap_status)
                    failure_type = request.env['sms.sms'].IAP_TO_SMS_FAILURE_TYPE.get(state, 'unknown')
                    sms_sudo.write({'state': 'error', 'failure_type': failure_type})
                    _logger.info(f"executed _action_update_from_provider_error")
            all_uuids.append(uuid)


    @staticmethod
    def _check_status_values(uuids, iap_status, message_statuses):
        """Basic checks to avoid unnecessary queries and allow debugging."""
        if (not uuids or not iap_status or not re.match(r'^\w+$', iap_status)
                or any(not re.match(r'^[0-9a-f]{32}$', uuid) for uuid in uuids)):
            _logger.warning('Received ill-formatted SMS delivery report event: \n%s', message_statuses)
            raise UserError("Bad parameters")
