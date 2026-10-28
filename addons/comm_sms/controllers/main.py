from odoo import http
from odoo.http import request, Response
import json
import logging
import re
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Africa's Talking delivery report status -> report status
# https://developers.africastalking.com/docs/sms/notifications
AFRICASTALKING_DLR_STATUS = {
    'Sent': 'pending',
    'Submitted': 'pending',
    'Buffered': 'pending',
    'Success': 'delivered',
    'Rejected': 'error',
    'Failed': 'error',
    'AbsentSubscriber': 'error',
    'Expired': 'error',
}
AFRICASTALKING_FAILURE_TYPE = {
    'InsufficientCredit': 'sms_credit',
    'UserInBlackList': 'sms_blacklist',
    'DoNotDisturbRejection': 'sms_blacklist',
    'UserDoesNotExist': 'sms_number_format',
    'NotNetworkSubscriber': 'sms_number_format',
}

# Connect Mobile delivery report status -> report status
CONNECT_MOBILE_DLR_STATUS = {
    'PENDING': 'pending',
    'DELIVERED': 'delivered',
    'FAILED': 'error',
    'REJECTED': 'error',
}


def _webhook_account(provider, required=True):
    """Account matching the callback's ?token=, or None when the token is
    missing/wrong. With required=False a missing token is let through (as an
    empty account) for callbacks configured before tokens existed."""
    token = request.httprequest.args.get('token')
    if not token:
        if required:
            _logger.warning("%s webhook called without token", provider)
            return None
        return request.env['comm.sms.account'].sudo().browse()
    account = request.env['comm.sms.account'].sudo().find_for_webhook_token(provider, token)
    if not account:
        _logger.warning("%s webhook called with unknown token", provider)
        return None
    return account


def _forbidden():
    return Response("Forbidden", status=403)


class InfoBipSMSControler(http.Controller):
    @http.route(['/sms/infobip/status'], type="http", auth="public", methods=['POST'], csrf=False)
    def update_sms_status(self, **kwargs):
        # Delivery reports for SMS sent before webhook tokens existed carry no
        # token, so only a wrong token is refused here.
        if _webhook_account('infobip', required=False) is None:
            return _forbidden()
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
        SmsSms = request.env['sms.sms']
        message_statuses = data.get('results') or []
        _logger.info(f"message_statuses: {message_statuses}")
        for status in message_statuses:
            uuid = status.get('messageId')
            group_name = (status.get('status') or {}).get('groupName')
            _logger.info(f"uuid: {uuid}, groupName: {group_name}")
            sms_sudo = SmsSms.sudo().search([('uuid', '=', uuid)]) if uuid else SmsSms
            if not sms_sudo:
                continue
            if group_name == 'DELIVERED':
                sms_sudo._apply_delivery_report('delivered')
            elif group_name == 'PENDING':
                sms_sudo._apply_delivery_report('pending')
            else:
                iap_failure = SmsSms.get_mapped_infobip_failure_type(status.get('error') or {})
                sms_sudo._apply_delivery_report(
                    'error', SmsSms.IAP_TO_SMS_FAILURE_TYPE.get(iap_failure, 'unknown'))


    @staticmethod
    def _check_status_values(uuids, iap_status, message_statuses):
        """Basic checks to avoid unnecessary queries and allow debugging."""
        if (not uuids or not iap_status or not re.match(r'^\w+$', iap_status)
                or any(not re.match(r'^[0-9a-f]{32}$', uuid) for uuid in uuids)):
            _logger.warning('Received ill-formatted SMS delivery report event: \n%s', message_statuses)
            raise UserError("Bad parameters")


class AfricasTalkingSMSController(http.Controller):

    @http.route(['/sms/africastalking/status'], type="http", auth="public", methods=['POST'], csrf=False)
    def africastalking_status(self, **kwargs):
        """Delivery report, form-encoded: id, status, phoneNumber, networkCode,
        failureReason, retryCount. `id` is the messageId returned at send."""
        if not _webhook_account('africastalking'):
            return _forbidden()
        _logger.info("Africa's Talking delivery report: %s", kwargs)
        message_id = kwargs.get('id')
        status = AFRICASTALKING_DLR_STATUS.get(kwargs.get('status'))
        if message_id and status:
            sms = request.env['sms.sms'].sudo().search([('provider_message_id', '=', message_id)])
            sms._apply_delivery_report(
                status, AFRICASTALKING_FAILURE_TYPE.get(kwargs.get('failureReason'), 'unknown'))
        return Response("OK", status=200)


class ConnectMobileSMSController(http.Controller):

    @http.route(['/sms/connectmobile/dlr'], type="http", auth="public", methods=['GET', 'POST'], csrf=False)
    def connect_mobile_dlr(self, **kwargs):
        """Delivery report as query parameters: status, smsid, userid, da,
        cost. `userid` is the uuid we sent as `id`; `smsid` their X-SMS-ID."""
        if not _webhook_account('connect_mobile'):
            return _forbidden()
        _logger.info("Connect Mobile delivery report: %s", kwargs)
        status = CONNECT_MOBILE_DLR_STATUS.get((kwargs.get('status') or '').upper())
        SmsSms = request.env['sms.sms'].sudo()
        sms = SmsSms.browse()
        if kwargs.get('userid'):
            sms = SmsSms.search([('uuid', '=', kwargs['userid'])])
        if not sms and kwargs.get('smsid'):
            sms = SmsSms.search([('provider_message_id', '=', kwargs['smsid'])])
        if sms and status:
            sms._apply_delivery_report(status)
        return Response("OK", status=200)
