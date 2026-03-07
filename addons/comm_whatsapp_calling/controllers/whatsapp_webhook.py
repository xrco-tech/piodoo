# -*- coding: utf-8 -*-

import json
import logging
from odoo import http
from odoo.http import request

from odoo.addons.comm_whatsapp.controllers.whatsapp_auth import WhatsAppAuthController

_logger = logging.getLogger(__name__)


def _parse_webhook_data():
    """Parse JSON body once for reuse."""
    data = request.httprequest.get_json(silent=True)
    if not data:
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return data


def _convert_timestamp(ts):
    """Convert Unix timestamp to naive UTC datetime (Odoo Datetime fields expect naive)."""
    if not ts:
        return False
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return False


class WhatsAppWebhookCalling(WhatsAppAuthController):
    """
    Extend comm_whatsapp webhook to handle 'calls' field.
    When Meta sends a change with field=='calls', we process it and return OK;
    otherwise we delegate to the parent (messages, etc.).
    """

    def _handle_webhook_event(self):
        data = _parse_webhook_data()
        if data.get("object") != "whatsapp_business_account":
            return super()._handle_webhook_event()

        had_calls = False
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "calls":
                    continue
                had_calls = True
                value = change.get("value", {})
                for call_data in value.get("calls", []):
                    try:
                        self._process_call_event(call_data, entry)
                    except Exception as e:
                        _logger.error(
                            "comm_whatsapp_calling: process_call_event error: %s",
                            e,
                            exc_info=True,
                        )

        if had_calls:
            return request.make_response(
                "OK", [("Content-Type", "text/plain")], status=200
            )
        return super()._handle_webhook_event()

    def _process_call_event(self, call_data, entry_data):
        call_id = call_data.get("id")
        if not call_id:
            _logger.warning("comm_whatsapp_calling: call event without id: %s", call_data)
            return

        event = call_data.get("event")
        status = None
        if event == "terminate":
            status = "ended"
        elif event == "connect":
            status = "ringing"

        CallLog = request.env["whatsapp.call.log"].sudo()
        existing = CallLog.search([("call_id", "=", call_id)], limit=1)

        if existing:
            metadata = entry_data.get("metadata", {}) or call_data.get("metadata", {})
            update_vals = {}
            if metadata.get("phone_number_id") and not existing.meta_phone_number_id:
                update_vals["meta_phone_number_id"] = str(metadata["phone_number_id"])
            self._update_call_log(existing, call_data, status, update_vals)
            if status == "ringing" and not existing.sdp_offer:
                offer_sdp = call_data.get("session", {}).get("sdp")
                if offer_sdp:
                    existing.write({"sdp_offer": offer_sdp, "call_status": "ringing"})
                    existing.action_pre_accept()
            return

        # Create new call log
        from_number = call_data.get("from", "")
        to_number = call_data.get("to", "")
        metadata = entry_data.get("metadata", {}) or call_data.get("metadata", {})
        meta_phone_number_id = metadata.get("phone_number_id")
        phone_number_id = meta_phone_number_id or to_number
        direction = "incoming" if call_data.get("direction") == "USER_INITIATED" else "outgoing"

        partner = self._find_or_create_partner(from_number)
        vals = {
            "call_id": call_id,
            "partner_id": partner.id if partner else False,
            "from_number": from_number,
            "to_number": to_number or str(phone_number_id),
            "call_direction": direction,
            "call_status": status or "ringing",
            "call_timestamp": _convert_timestamp(call_data.get("timestamp")),
            "raw_data": json.dumps(call_data),
        }
        if meta_phone_number_id:
            vals["meta_phone_number_id"] = str(meta_phone_number_id)
        offer_sdp = call_data.get("session", {}).get("sdp")
        if offer_sdp:
            vals["sdp_offer"] = offer_sdp

        call_log = CallLog.create(vals)
        if offer_sdp:
            call_log.action_pre_accept()

    def _update_call_log(self, call_log, call_data, status, extra_vals=None):
        if not status and not extra_vals:
            return
        write_vals = dict(extra_vals or {})
        if status:
            write_vals["call_status"] = status
            write_vals["raw_data"] = json.dumps(call_data)
            if status == "ended":
                write_vals["end_timestamp"] = _convert_timestamp(call_data.get("timestamp"))
                write_vals["duration"] = call_data.get("duration", 0)
        if write_vals:
            call_log.write(write_vals)

    def _find_or_create_partner(self, phone_number):
        if not phone_number:
            return request.env["res.partner"].browse()
        clean = phone_number.replace("+", "").replace(" ", "").replace("-", "")
        Partner = request.env["res.partner"].sudo()
        partner = Partner.search(
            [
                "|",
                ("phone", "ilike", f"%{clean}%"),
                ("mobile", "ilike", f"%{clean}%"),
            ],
            limit=1,
        )
        if partner:
            return partner
        return Partner.create({
            "name": f"WhatsApp {phone_number}",
            "mobile": phone_number,
            "is_company": False,
        })
