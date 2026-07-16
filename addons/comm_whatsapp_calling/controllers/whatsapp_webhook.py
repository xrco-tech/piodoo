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
        meta_direction = call_data.get("direction")
        _logger.info(
            "comm_whatsapp_calling: call event id=%s event=%s "
            "direction=%s from=%s to=%s has_session=%s",
            call_id, event, meta_direction,
            call_data.get("from"), call_data.get("to"),
            bool((call_data.get("session") or {}).get("sdp")),
        )
        # Meta's Business Calling event vocabulary is direction-sensitive.
        # For an outbound call (BUSINESS_INITIATED) the recipient's
        # ANSWER comes back on the same `connect` event that inbound
        # calls use for their initial ring. Route by direction:
        #   BUSINESS_INITIATED + connect  → outbound answered (has SDP)
        #   USER_INITIATED     + connect  → inbound ringing (has SDP)
        status = None
        is_outbound_meta = (meta_direction == "BUSINESS_INITIATED")
        if event in ("terminate", "hangup"):
            status = "ended"
        elif event == "reject":
            status = "ended"
        elif event == "connect":
            status = "answered" if is_outbound_meta else "ringing"
        elif event in ("accept", "answered", "session_established",
                       "session_start"):
            status = "answered"

        if not status:
            _logger.warning(
                "comm_whatsapp_calling: unrecognised event %r on call %s. "
                "Full payload: %s",
                event, call_id, call_data,
            )

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
                    # pre_accept requires an SDP answer we don't have
                    # server-side (the browser generates it on Accept);
                    # skip straight to the ringing bus push.
                    self._send_ringing_notification(existing)
            # Outbound flow: the remote answered. Push the SDP answer
            # to the browser so it can call setRemoteDescription and
            # kick off DTLS-SRTP.
            if status == "answered" and existing.call_direction == "outgoing":
                answer_sdp = call_data.get("session", {}).get("sdp")
                if answer_sdp:
                    existing.write({
                        "sdp_answer":  answer_sdp,
                        "call_status": "answered",
                    })
                    self._send_outbound_answered_notification(existing, answer_sdp)
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
        # pre_accept is skipped intentionally — Meta requires an SDP
        # answer with it, which only the browser can generate. The user
        # clicking Accept produces the real SDP; the accept POST alone
        # is sufficient for Meta to establish the DTLS-SRTP session.
        if call_log.call_status == "ringing":
            self._send_ringing_notification(call_log)

    def _resolve_suggested_voice_script(self, partner):
        """If this caller belongs to a campaign with a linked voice script,
        return (chatbot_id, chatbot_name) for the ringing popup to suggest -
        else (False, ""). contact_centre is an optional layer on top of this
        module (not a manifest dependency), so this checks the model exists
        rather than importing it, and never raises into the call flow."""
        if not partner or "contact.centre.contact" not in request.env:
            return False, ""
        try:
            contact = request.env["contact.centre.contact"].sudo().search(
                [("partner_id", "=", partner.id)], limit=1)
            if not contact:
                return False, ""
            campaign = request.env["contact.centre.campaign"].sudo().search([
                ("contact_ids", "in", [contact.id]),
                ("voice_chatbot_id", "!=", False),
            ], order="id desc", limit=1)
            if campaign:
                return campaign.voice_chatbot_id.id, campaign.voice_chatbot_id.name
        except Exception as e:
            _logger.warning(
                "comm_whatsapp_calling: could not resolve suggested voice script: %s", e
            )
        return False, ""

    def _send_ringing_notification(self, call_log):
        """Notify connected users of an incoming (ringing) WhatsApp call via bus."""
        try:
            if "bus.bus" not in request.env:
                return
            partner = call_log.partner_id
            partner_name = partner.name if partner else call_log.from_number or "Unknown"
            suggested_chatbot_id, suggested_chatbot_name = self._resolve_suggested_voice_script(partner)
            payload = {
                "type": "whatsapp_incoming_call",
                "call_log_id": call_log.id,
                "partner_id": partner.id if partner else False,
                "partner_name": partner_name,
                "from_number": call_log.from_number or "",
                "call_timestamp": (
                    call_log.call_timestamp.isoformat()
                    if call_log.call_timestamp
                    else None
                ),
                # Ship the raw SDP offer to the browser so the popup can
                # build a real RTCPeerConnection the moment the user
                # clicks Accept — no round-trip needed to fetch it.
                "sdp_offer": call_log.sdp_offer or "",
                # Set only when this caller belongs to a campaign with a
                # linked voice script - see _resolve_suggested_voice_script.
                "suggested_chatbot_id": suggested_chatbot_id,
                "suggested_chatbot_name": suggested_chatbot_name,
            }
            # Routing rules first — a matching rule narrows the ring to
            # a specific agent set. When no rule matches (or the match
            # resolves to zero currently-available users), fall back to
            # broadcasting to every Available user so no install ever
            # silently drops a call.
            Rule = request.env["whatsapp.call.routing.rule"].sudo()
            users = Rule.resolve_target_users(
                call_log.account_id.id if call_log.account_id else False,
                call_log.from_number or "",
            )
            if not users:
                users = request.env["res.users"].sudo().search([
                    ("active", "=", True),
                    ("wa_call_presence", "=", "available"),
                ])
            bus = request.env["bus.bus"].sudo()
            # Target the user's partner record — Odoo 18 auto-subscribes
            # each authenticated session to its partner channel, so this
            # is the only reliably-delivered target for a per-user push.
            n_users = 0
            for u in users:
                partner = u.partner_id
                if not partner:
                    continue
                try:
                    bus._sendone(
                        partner,                       # target = partner record
                        "whatsapp_incoming_call",      # notification_type
                        payload,                       # message
                    )
                    n_users += 1
                except AttributeError:
                    _logger.warning(
                        "comm_whatsapp_calling: bus.bus._sendone missing; cannot notify user %s",
                        u.id,
                    )
                    break
            if n_users:
                _logger.info(
                    "comm_whatsapp_calling: sent ringing notification for call %s to %s users",
                    call_log.call_id,
                    n_users,
                )
        except Exception as e:
            _logger.warning(
                "comm_whatsapp_calling: could not send ringing notification: %s", e
            )

    def _send_outbound_answered_notification(self, call_log, answer_sdp):
        """The remote party accepted an outbound call and Meta forwarded
        us their SDP answer. Push it to every logged-in user's partner
        channel so whoever initiated the call gets it in their browser
        and can call setRemoteDescription on the RTCPeerConnection they
        opened when they clicked Call.
        """
        try:
            if "bus.bus" not in request.env:
                return
            payload = {
                "type":         "whatsapp_outbound_answered",
                "call_log_id":  call_log.id,
                "sdp_answer":   answer_sdp,
                "to_number":    call_log.to_number or "",
            }
            users = request.env["res.users"].sudo().search([("active", "=", True)])
            bus = request.env["bus.bus"].sudo()
            for u in users:
                partner = u.partner_id
                if not partner:
                    continue
                try:
                    bus._sendone(partner, "whatsapp_outbound_answered", payload)
                except AttributeError:
                    break
            _logger.info(
                "comm_whatsapp_calling: pushed outbound-answered SDP for call %s",
                call_log.call_id,
            )
        except Exception as e:
            _logger.warning(
                "comm_whatsapp_calling: could not push outbound-answered SDP: %s", e
            )

    def _update_call_log(self, call_log, call_data, status, extra_vals=None):
        if not status and not extra_vals:
            return
        write_vals = dict(extra_vals or {})
        if status:
            # Always store the last webhook payload for debugging/auditing.
            write_vals["raw_data"] = json.dumps(call_data)

            if status == "ended":
                # Terminal event: do not overwrite final decision made earlier
                # (e.g. "answered" / "declined") with a generic "ended".
                if call_log.call_status not in ("answered", "declined"):
                    write_vals["call_status"] = status
            else:
                write_vals["call_status"] = status

            if status == "ended":
                write_vals["end_timestamp"] = _convert_timestamp(call_data.get("timestamp"))
                # Prefer Meta's duration; otherwise derive from timestamps
                # so the log is still complete for reporting.
                meta_duration = call_data.get("duration")
                if meta_duration:
                    write_vals["duration"] = meta_duration
                elif call_log.call_timestamp and write_vals.get("end_timestamp"):
                    delta = write_vals["end_timestamp"] - call_log.call_timestamp
                    write_vals["duration"] = max(int(delta.total_seconds()), 0)
        if write_vals:
            call_log.write(write_vals)
        # Remote hangup / rejection — tell any browser still showing the
        # popup that this call is gone so it disappears without waiting
        # for a click.
        if status == "ended":
            try:
                call_log._broadcast_call_taken("remote_ended")
            except Exception:
                pass
            # Voicemail: when an inbound call ends without ever being
            # answered, send the account's canned message to the caller
            # so they know we saw the miss.
            self._maybe_send_voicemail(call_log)

    def _maybe_send_voicemail(self, call_log):
        try:
            if call_log.voicemail_sent:
                return
            if call_log.call_direction != "incoming":
                return
            # Only genuine misses: an answered call that later ended is
            # a normal hangup, not a voicemail trigger.
            if call_log.call_status not in ("ended", "ringing", "failed"):
                return
            if call_log.is_missed is False:
                # is_missed is computed; guard against edge cases.
                return
            acc = call_log.account_id
            if not acc or not acc.voicemail_enabled:
                return
            if not (acc.voicemail_message or "").strip():
                return
            result = acc.send_text_message(
                call_log.from_number, acc.voicemail_message,
            )
            if result:
                call_log.write({"voicemail_sent": True})
                _logger.info(
                    "comm_whatsapp_calling: voicemail sent for call %s to %s",
                    call_log.call_id, call_log.from_number,
                )
        except Exception as e:
            _logger.warning(
                "comm_whatsapp_calling: voicemail dispatch failed: %s", e
            )

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
