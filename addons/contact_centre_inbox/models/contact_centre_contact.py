# -*- coding: utf-8 -*-

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ContactCentreContact(models.Model):
    _inherit = 'contact.centre.contact'

    def action_send_reply(self, channel, body):
        """Send a manual agent reply on the given channel and log it.
        Public (no leading underscore) since it's called from the inbox's
        composer button."""
        self.ensure_one()
        if not body:
            return False
        if channel == 'whatsapp':
            return self._send_reply_whatsapp(body)
        elif channel == 'sms':
            return self._send_reply_sms(body)
        return False

    def _send_reply_whatsapp(self, body):
        phone = self.phone_number
        bsuid = self.bsuid
        if not phone and not bsuid:
            _logger.warning(
                "Inbox: contact %s has no phone number or WhatsApp ID, skipping WA reply.",
                self.id)
            return False

        account = self.env['comm.whatsapp.account'].sudo().get_default()
        result = self.env['whatsapp.message'].sudo().send_whatsapp_message(
            recipient_phone=phone,
            message_text=body,
            account=account,
            bsuid=bsuid,
        )
        success = isinstance(result, dict) and result.get('success', False)
        status = 'sent' if success else 'failed'
        failure = result.get('error', '') if isinstance(result, dict) and not success else ''

        self.env['contact.centre.message'].sudo().create({
            'contact_id': self.id,
            'channel': 'whatsapp',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'provider_message_id': result.get('message_id', '') if isinstance(result, dict) else '',
            'message_timestamp': fields.Datetime.now(),
        })
        return success

    def _send_reply_sms(self, body):
        phone = self.phone_number
        if not phone:
            _logger.warning("Inbox: contact %s has no phone number, skipping SMS reply.", self.id)
            return False

        sms = self.env['sms.sms'].sudo().create({
            'number': phone,
            'body': body,
            'state': 'outgoing',
        })
        try:
            sms._send()
            status = 'sent'
            failure = ''
        except Exception as e:
            status = 'failed'
            failure = str(e)

        self.env['contact.centre.message'].sudo().create({
            'contact_id': self.id,
            'channel': 'sms',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'message_timestamp': fields.Datetime.now(),
        })
        return status == 'sent'
