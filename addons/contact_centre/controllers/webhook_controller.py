# -*- coding: utf-8 -*-

import json
import logging
import re
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class ContactCentreWebhookController(http.Controller):
    """Unified webhook controller for WhatsApp, SMS and Email"""

    # -------------------------------------------------------------------------
    # WhatsApp webhook
    # -------------------------------------------------------------------------

    @http.route('/contact_centre/webhook/whatsapp', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def whatsapp_webhook(self, **kwargs):
        """Handle incoming WhatsApp webhooks (Meta Cloud API format)."""
        # GET: webhook verification challenge
        if request.httprequest.method == 'GET':
            mode = kwargs.get('hub.mode')
            token = kwargs.get('hub.verify_token')
            challenge = kwargs.get('hub.challenge')
            expected_token = request.env['ir.config_parameter'].sudo().get_param(
                'whatsapp.external_trigger_api_key', default=False)
            if mode == 'subscribe' and token == expected_token:
                return request.make_response(challenge, headers={'Content-Type': 'text/plain'})
            return request.make_response('Forbidden', status=403)

        # POST: incoming message events
        try:
            raw_data = request.httprequest.data.decode('utf-8')
            data = json.loads(raw_data)
            _logger.info("WhatsApp webhook received: %s", data)
            self._process_whatsapp_webhook(data)
        except Exception as e:
            _logger.error("Error processing WhatsApp webhook: %s", e)

        return request.make_response(
            json.dumps({'status': 'ok'}),
            headers={'Content-Type': 'application/json'}
        )

    def _process_whatsapp_webhook(self, data):
        """
        Process Meta Cloud API webhook payload.
        Creates contact.centre.message records for inbound messages and
        updates existing records on status changes.
        """
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                # Delivery / read status updates
                for status in value.get('statuses', []):
                    self._handle_whatsapp_status_update(status)
                # BSUID rotation — Meta can reassign a user's business-
                # scoped user ID; without this, a stored bsuid silently
                # goes stale.
                if 'user_id_update' in value:
                    self._handle_user_id_update(value['user_id_update'])
                # Inbound messages. .get('wa_id') rather than direct
                # indexing — a contact who's gone quiet 30+ days after
                # adopting a username has phone fields (including this
                # one) omitted from the webhook entirely, so this key
                # can legitimately be absent.
                contacts_map = {
                    c['wa_id']: c.get('profile', {}).get('name', '')
                    for c in value.get('contacts', []) if c.get('wa_id')
                }
                # Meta's business-scoped user ID, keyed the same way —
                # see _get_or_create_contact for why this is captured.
                bsuid_map = {
                    c['wa_id']: c.get('user_id')
                    for c in value.get('contacts', [])
                    if c.get('wa_id') and c.get('user_id')
                }
                for msg in value.get('messages', []):
                    self._handle_whatsapp_inbound(msg, contacts_map, bsuid_map)

    def _handle_whatsapp_status_update(self, status):
        """Update contact.centre.message status from a WhatsApp delivery event."""
        provider_msg_id = status.get('id')
        raw_status = status.get('status')  # sent / delivered / read / failed
        if not provider_msg_id or not raw_status:
            return
        status_map = {
            'sent': 'sent',
            'delivered': 'delivered',
            'read': 'read',
            'failed': 'failed',
        }
        mapped = status_map.get(raw_status)
        if not mapped:
            return
        cc_msg = request.env['contact.centre.message'].sudo().search(
            [('provider_message_id', '=', provider_msg_id)], limit=1)
        if cc_msg:
            cc_msg.write({'status': mapped})

    def _handle_user_id_update(self, event):
        """Meta fires this when a WhatsApp user's business-scoped user
        ID (bsuid) changes — re-point every contact still on the old
        value so future sends targeting it don't silently start
        failing. Payload shape: {"user_id": {"previous": ..., "current":
        ...}, ...}.

        See: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
        """
        try:
            user_id = event.get('user_id', {}) or {}
            previous_bsuid = user_id.get('previous')
            current_bsuid = user_id.get('current')
            if not previous_bsuid or not current_bsuid:
                _logger.warning(
                    "user_id_update event missing previous/current: %s", event)
                return
            request.env['contact.centre.contact'].sudo()._handle_wa_bsuid_rotation(
                previous_bsuid, current_bsuid)
            _logger.info("BSUID rotated: %s -> %s", previous_bsuid, current_bsuid)
        except Exception as e:
            _logger.error("Error processing user_id_update: %s", e)

    def _handle_whatsapp_inbound(self, msg, contacts_map, bsuid_map=None):
        """Create a contact.centre.message record for an inbound WhatsApp message."""
        sender_wa_id = msg.get('from')
        sender_name = contacts_map.get(sender_wa_id, sender_wa_id)
        sender_bsuid = (bsuid_map or {}).get(sender_wa_id) or msg.get('from_user_id')
        msg_type = msg.get('type', 'text')

        body = ''
        if msg_type == 'text':
            body = msg.get('text', {}).get('body', '')
        elif msg_type == 'button':
            body = msg.get('button', {}).get('text', '')
        elif msg_type == 'interactive':
            interactive = msg.get('interactive', {})
            itype = interactive.get('type')
            if itype == 'button_reply':
                body = interactive.get('button_reply', {}).get('title', '')
            elif itype == 'list_reply':
                body = interactive.get('list_reply', {}).get('title', '')
        elif msg_type in ('image', 'video', 'audio', 'document', 'sticker'):
            body = msg.get(msg_type, {}).get('caption', '') or f'[{msg_type}]'
        elif msg_type == 'location':
            loc = msg.get('location', {})
            body = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"

        # Resolve or create contact
        contact = self._get_or_create_contact(phone=sender_wa_id, name=sender_name, bsuid=sender_bsuid)
        if not contact:
            return

        cc_msg_type = msg_type if msg_type in ('text', 'image', 'video', 'audio', 'document') else 'interactive'
        cc_msg = request.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'channel': 'whatsapp',
            'direction': 'inbound',
            'message_type': cc_msg_type,
            'body_text': body,
            'status': 'delivered',
            'provider_message_id': msg.get('id'),
            'message_timestamp': fields.Datetime.now(),
        })

        # Route through chatbot if one is active for this contact/channel
        handled = False
        try:
            handled = request.env['contact.centre.chatbot'].sudo().route_inbound(
                contact, 'whatsapp', body, cc_message=cc_msg
            )
        except Exception as e:
            _logger.error("Chatbot routing error (WhatsApp): %s", e)

        # No chatbot matched — fall back to a keyword/inbound automation reply
        if not handled:
            try:
                request.env['contact.centre.automation'].sudo().check_and_fire(
                    contact, 'whatsapp', body, cc_message=cc_msg
                )
            except Exception as e:
                _logger.error("Automation firing error (WhatsApp): %s", e)

    # -------------------------------------------------------------------------
    # SMS webhook (InfoBip delivery reports – mirrors comm_sms logic)
    # -------------------------------------------------------------------------

    @http.route('/contact_centre/webhook/sms', type='http', auth='public', methods=['POST'], csrf=False)
    def sms_webhook(self, **kwargs):
        """Handle incoming SMS webhooks from InfoBip (delivery reports + inbound MO messages)."""
        try:
            content_type = request.httprequest.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                raw_data = request.httprequest.data.decode('utf-8')
                data = json.loads(raw_data)
                _logger.info("SMS webhook received: %s", data)
                # InfoBip sends inbound MO messages under 'results' with a 'from' field
                # Delivery reports also use 'results' but have 'status.groupName'
                self._process_sms_webhook(data)
            else:
                _logger.info("SMS webhook form data: %s", kwargs)
        except Exception as e:
            _logger.error("Error processing SMS webhook: %s", e)
            return request.make_response(
                json.dumps({'error': str(e)}),
                status=500,
                headers={'Content-Type': 'application/json'}
            )

        return request.make_response(
            json.dumps({'status': 'ok'}),
            headers={'Content-Type': 'application/json'}
        )

    def _process_sms_webhook(self, data):
        """
        Process InfoBip webhook payload.

        InfoBip uses the same /results array structure for both delivery reports
        and inbound MO messages.  We distinguish them by the presence of 'from'
        (inbound MO) vs 'messageId' with a status.groupName (delivery report).
        """
        results = data.get('results', [])
        for result in results:
            msg_id = result.get('messageId')
            from_number = result.get('from')
            status_group = result.get('status', {}).get('groupName', '').lower()
            error_name = result.get('error', {}).get('name', 'NO_ERROR')

            # --- Inbound MO message ---
            if from_number and result.get('text') is not None:
                self._handle_sms_inbound(result)
                continue

            if not msg_id:
                continue

            # --- Delivery report ---
            sms_sudo = request.env['sms.sms'].sudo().search([('uuid', '=', msg_id)], limit=1)
            if sms_sudo:
                SmsModel = request.env['sms.sms']
                if state := SmsModel.IAP_TO_SMS_STATE_SUCCESS.get(status_group):
                    sms_sudo.sms_tracker_id._action_update_from_sms_state(state)
                    sms_sudo.write({'state': state, 'failure_type': False})
                else:
                    sms_sudo.sms_tracker_id._action_update_from_provider_error(status_group)
                    failure_type = SmsModel.IAP_TO_SMS_FAILURE_TYPE.get(status_group, 'unknown')
                    sms_sudo.write({'state': 'error', 'failure_type': failure_type})

            cc_msg = request.env['contact.centre.message'].sudo().search(
                [('provider_message_id', '=', msg_id)], limit=1)
            if cc_msg:
                if status_group == 'delivered':
                    cc_msg.write({'status': 'delivered'})
                elif status_group in ('undeliverable', 'expired', 'rejected'):
                    cc_msg.write({'status': 'failed', 'failure_reason': error_name})

    def _handle_sms_inbound(self, result):
        """Create a contact.centre.message for an inbound InfoBip MO SMS and route to chatbot."""
        from_number = result.get('from', '')
        body = result.get('text', '')
        msg_id = result.get('messageId', '')

        contact = self._get_or_create_contact(phone=from_number)
        if not contact:
            return

        cc_msg = request.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'channel': 'sms',
            'direction': 'inbound',
            'message_type': 'text',
            'body_text': body,
            'status': 'delivered',
            'provider_message_id': msg_id,
            'message_timestamp': fields.Datetime.now(),
        })

        # Route through chatbot
        handled = False
        try:
            handled = request.env['contact.centre.chatbot'].sudo().route_inbound(
                contact, 'sms', body, cc_message=cc_msg
            )
        except Exception as e:
            _logger.error("Chatbot routing error (SMS): %s", e)

        # No chatbot matched — fall back to a keyword/inbound automation reply
        if not handled:
            try:
                request.env['contact.centre.automation'].sudo().check_and_fire(
                    contact, 'sms', body, cc_message=cc_msg
                )
            except Exception as e:
                _logger.error("Automation firing error (SMS): %s", e)

    # -------------------------------------------------------------------------
    # Email webhook
    # -------------------------------------------------------------------------

    @http.route('/contact_centre/webhook/email', type='json', auth='public', methods=['POST'], csrf=False)
    def email_webhook(self):
        """Handle incoming email webhooks (e.g. from mail gateway)."""
        data = request.jsonrequest
        _logger.info("Email webhook received: %s", data)
        return {'status': 'ok'}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_or_create_contact(self, phone, name=None, bsuid=None):
        """
        Find an existing contact.centre.contact by phone number or create one
        (also creating a res.partner if needed). `bsuid` is Meta's
        business-scoped user ID, when the webhook included one — see
        contact_centre_contact.py's bsuid field for why it's captured
        here rather than assumed to always be absent.

        `phone` may be falsy — once a WhatsApp user adopts a username
        and goes 30+ days without interacting with this business
        number, Meta omits phone-number fields from webhooks entirely.
        Falls through to a bsuid lookup/create in that case rather than
        matching every other phone-less contact on an empty string.
        """
        # Normalize phone: strip spaces/dashes, ensure leading +
        normalized = re.sub(r'[\s\-()]', '', phone or '')
        if normalized and not normalized.startswith('+'):
            normalized = '+' + normalized

        # Try to find existing CC contact
        if normalized:
            cc_contact = request.env['contact.centre.contact'].sudo().search(
                [('phone_number', '=', normalized)], limit=1)
            if cc_contact:
                if bsuid and cc_contact.bsuid != bsuid:
                    cc_contact.write({'bsuid': bsuid})
                return cc_contact

        if bsuid:
            cc_contact = request.env['contact.centre.contact'].sudo().search(
                [('bsuid', '=', bsuid)], limit=1)
            if cc_contact:
                if normalized and cc_contact.phone_number != normalized:
                    # Phone reappeared for a contact we'd only known by bsuid.
                    cc_contact.partner_id.write({'mobile': normalized})
                return cc_contact

        if not normalized and not bsuid:
            return None

        # Try to find by partner mobile
        partner = request.env['res.partner'].browse()
        if normalized:
            partner = request.env['res.partner'].sudo().search(
                [('mobile', '=', normalized)], limit=1)
        if not partner:
            partner = request.env['res.partner'].sudo().create({
                'name': name or normalized or 'WhatsApp Contact',
                'mobile': normalized or False,
            })

        cc_contact = request.env['contact.centre.contact'].sudo().create({
            'partner_id': partner.id,
            'bsuid': bsuid,
        })
        return cc_contact
