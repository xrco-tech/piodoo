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
    _name = "contact.centre.contact"
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

    def _find_or_create_by_phone(self, phone_number, source_label, bsuid=None):
        """`bsuid` is Meta's business-scoped user ID, when the caller
        already has one (e.g. from whatsapp.message.bsuid) — stored on
        both the partner (comm_whatsapp's wa_bsuid, shared with the
        calling/chatbot modules) and this contact (contact_centre's own
        bsuid, since this module is the only place both fields are
        reachable at once). See either field's own module for why
        there isn't just one.

        `phone_number` may be falsy — once a WhatsApp user adopts a
        username and goes 30+ days without interacting with this
        business number, Meta omits phone-number fields from webhooks
        entirely and only bsuid survives. Falls through to a bsuid
        lookup/create in that case instead of returning nothing."""
        clean = re.sub(r"\D", "", phone_number or "")
        Partner = self.env["res.partner"].sudo()
        partner = Partner.browse()
        if clean:
            partner = Partner.search([
                "|", ("phone", "ilike", clean), ("mobile", "ilike", clean),
            ], limit=1)
        if not partner and bsuid:
            partner = Partner.search([("wa_bsuid", "=", bsuid)], limit=1)
        if not partner:
            partner = Partner.create({
                "name": f"{source_label} {phone_number or bsuid}",
                "mobile": phone_number or False,
                "is_company": False,
                "wa_bsuid": bsuid,
            })
        elif bsuid and partner.wa_bsuid != bsuid:
            partner.write({"wa_bsuid": bsuid})
        contact = self._find_or_create_contact_for_partner(partner)
        if bsuid and contact.bsuid != bsuid:
            contact.write({"bsuid": bsuid})
        return contact

    @api.model
    def _sync_whatsapp_message(self, wa_message):
        phone = wa_message.phone_number or wa_message.wa_id
        if not phone and not wa_message.bsuid:
            return
        contact = self._find_or_create_by_phone(phone, "WhatsApp", bsuid=wa_message.bsuid)
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

    @api.model
    def _backfill_missed_call_mislabeling(self):
        """One-shot correction for calls that were actually answered but
        got permanently mislabeled "Missed call" in the Inbox.

        Root cause (fixed alongside this in comm_whatsapp_calling's
        action_hangup): hanging up an answered call unconditionally
        overwrote call_status from "answered" to the generic "ended",
        and is_missed treats "ended" as never-picked-up. The original
        "answered" marker is gone by the time we get here, so duration
        > 0 or an attached recording stand in as proof the call was
        genuinely answered (both are impossible unless it connected).
        """
        CallLog = self.env["whatsapp.call.log"].sudo()
        mislabeled = CallLog.search([
            ("call_direction", "=", "incoming"),
            ("call_status", "=", "ended"),
        ])
        truly_answered = mislabeled.filtered(lambda c: c.duration > 0 or c.recording_ids)
        if not truly_answered:
            return
        truly_answered.write({"call_status": "answered"})
        for call_log in truly_answered:
            self._sync_whatsapp_call(call_log)
