# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models

# contact.centre.message.message_type only accepts these values; whatsapp.message
# has a wider vocabulary (e.g. "reaction") that has no equivalent here.
_WA_TO_CENTRE_MESSAGE_TYPE = {
    "text": "text",
    "image": "image",
    "video": "video",
    "audio": "audio",
    "document": "document",
    "location": "location",
    "template": "template",
    "interactive": "interactive",
}


class ContactCentreContact(models.Model):
    _inherit = ["contact.centre.contact", "mail.thread", "mail.activity.mixin"]

    state = fields.Selection([
        ("open", "Open"),
        ("pending", "Pending"),
        ("resolved", "Resolved"),
    ], default="open", tracking=True)

    def _find_or_create_contact_for_partner(self, partner):
        contact = self.sudo().search([("partner_id", "=", partner.id)], limit=1)
        if not contact:
            contact = self.sudo().create({"partner_id": partner.id})
        return contact

    def _find_or_create_by_phone(self, phone_number, source_label):
        clean = re.sub(r"\D", "", phone_number or "")
        Partner = self.env["res.partner"].sudo()
        partner = Partner.browse()
        if clean:
            partner = Partner.search([
                "|", ("phone", "ilike", clean), ("mobile", "ilike", clean),
            ], limit=1)
        if not partner:
            partner = Partner.create({
                "name": f"{source_label} {phone_number}",
                "mobile": phone_number,
                "is_company": False,
            })
        return self._find_or_create_contact_for_partner(partner)

    @api.model
    def _sync_whatsapp_message(self, wa_message):
        phone = wa_message.phone_number or wa_message.wa_id
        if not phone:
            return
        contact = self._find_or_create_by_phone(phone, "WhatsApp")
        direction = "inbound" if wa_message.is_incoming else "outbound"
        message_type = _WA_TO_CENTRE_MESSAGE_TYPE.get(wa_message.message_type, "text")
        self.env["contact.centre.message"].sudo().create({
            "contact_id": contact.id,
            "channel": "whatsapp",
            "direction": direction,
            "message_type": message_type,
            "body_text": wa_message.message_body,
            "status": "delivered" if wa_message.is_incoming else "sent",
            "message_timestamp": wa_message.message_timestamp or fields.Datetime.now(),
            "provider_message_id": wa_message.message_id,
            "whatsapp_message_id": wa_message.id,
        })

    def _call_summary(self, call_log, direction):
        label = "Incoming call" if direction == "inbound" else "Outgoing call"
        if call_log.is_missed:
            return "Missed call"
        if call_log.duration:
            minutes, seconds = divmod(int(call_log.duration), 60)
            return f"{label}, {minutes}:{seconds:02d}"
        return f"{label} ({call_log.call_status})"

    @api.model
    def _sync_whatsapp_call(self, call_log):
        if not call_log.partner_id:
            return
        contact = self._find_or_create_contact_for_partner(call_log.partner_id)
        direction = "inbound" if call_log.call_direction == "incoming" else "outbound"
        Message = self.env["contact.centre.message"].sudo()
        existing = Message.search([("whatsapp_call_log_id", "=", call_log.id)], limit=1)
        vals = {
            "contact_id": contact.id,
            "channel": "voice",
            "direction": direction,
            "message_type": "text",
            "body_text": self._call_summary(call_log, direction),
            "status": "delivered",
            "message_timestamp": call_log.call_timestamp or fields.Datetime.now(),
            "provider_message_id": call_log.call_id,
            "whatsapp_call_log_id": call_log.id,
        }
        if existing:
            existing.write(vals)
        else:
            Message.create(vals)
