# -*- coding: utf-8 -*-

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ContactCentreContact(models.Model):
    _inherit = 'contact.centre.contact'

    # Bridge the shared disposition taxonomy (comm.disposition, from
    # comm_whatsapp_calling — a dependency of this module) onto the Gen-1
    # contact thread, so the CC inbox can wrap up a conversation with the
    # same outcome codes as calls and the Gen-2 inbox.
    disposition_id = fields.Many2one(
        'comm.disposition', string='Disposition', ondelete='set null', index=True,
        help='Outcome / wrap-up code the agent set for this conversation.')
    disposition_note = fields.Text('Disposition Note')

    def action_set_disposition(self, disposition_id, note=None):
        """Set (or clear) the disposition on this contact. Called from the
        inbox picker."""
        self.ensure_one()
        vals = {'disposition_id': disposition_id or False}
        if note is not None:
            vals['disposition_note'] = note
        self.write(vals)
        return True

    def _template_address_error(self, channel):
        """Human-readable reason this contact can't receive a template on
        `channel` (missing address), or '' when it can."""
        self.ensure_one()
        if channel == "email" and not self.email:
            return "This contact has no email address set, so an email template cannot be sent."
        if channel == "sms" and not self.phone_number:
            return "This contact has no phone number set, so an SMS template cannot be sent."
        if channel == "whatsapp" and not self.phone_number and not self.bsuid:
            return "This contact has no WhatsApp number set, so a WhatsApp template cannot be sent."
        return ""

    def action_send_template(self, template_id):
        """Send a contact.centre.template to this contact on the template's
        channel. Validates the contact has the required address first —
        returns {'error': msg} when it doesn't — else sends, logs a
        contact.centre.message, and returns {'success': True}.

        Sends the template body as the message (same path campaigns use);
        native WhatsApp template dispatch via wa_template_id can be layered
        on later."""
        self.ensure_one()
        template = self.env["contact.centre.template"].browse(int(template_id))
        if not template.exists():
            return {"error": "Template not found."}
        channel = template.channel
        err = self._template_address_error(channel)
        if err:
            return {"error": err}

        body = template.body_text or ""
        Message = self.env["contact.centre.message"].sudo()
        base = {
            "contact_id": self.id, "direction": "outbound", "message_type": "text",
            "body_text": body, "template_id": template.id,
            "message_timestamp": fields.Datetime.now(),
        }

        if channel == "whatsapp":
            account = self.env["comm.whatsapp.account"].sudo().get_default()
            result = self.env["whatsapp.message"].sudo().send_whatsapp_message(
                recipient_phone=self.phone_number, message_text=body,
                account=account, bsuid=self.bsuid,
            )
            ok = isinstance(result, dict) and result.get("success", False)
            Message.create({
                **base, "channel": "whatsapp",
                "status": "sent" if ok else "failed",
                "failure_reason": "" if ok else (result.get("error", "") if isinstance(result, dict) else ""),
                "provider_message_id": result.get("message_id", "") if isinstance(result, dict) else "",
            })
        elif channel == "sms":
            sms = self.env["sms.sms"].sudo().create(
                {"number": self.phone_number, "body": body, "state": "outgoing"})
            try:
                sms._send()
                status, failure = "sent", ""
            except Exception as e:  # noqa: BLE001 — surface the provider reason
                status, failure = "failed", str(e)
            Message.create({**base, "channel": "sms", "status": status,
                            "failure_reason": failure, "sms_id": sms.id})
        elif channel == "email":
            mail = self.env["mail.mail"].sudo().create({
                "subject": template.name, "body_html": "<p>%s</p>" % body,
                "email_to": self.email, "auto_delete": False,
            })
            try:
                mail.send()
                status, failure = "sent", ""
            except Exception as e:  # noqa: BLE001
                status, failure = "failed", str(e)
            Message.create({**base, "channel": "email", "status": status,
                            "failure_reason": failure})
        return {"success": True}

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
