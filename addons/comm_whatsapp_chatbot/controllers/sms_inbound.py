# -*- coding: utf-8 -*-
"""Inbound SMS (MO) webhook for Infobip.

Infobip's mobile-originated subscription POSTs JSON shaped roughly:

    {
      "results": [
        {
          "messageId": "...",
          "from": "27683264051",
          "to": "...",
          "cleanText": "Hi",
          "text": "Hi",
          "receivedAt": "...",
          ...
        },
        ...
      ]
    }

We accept either an envelope with `results: [...]` or a single message object,
extract sender + body, and hand off to whatsapp.chatbot.message
.process_incoming_sms_message which dispatches into the SMS-channel flow.
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class InfobipMOController(http.Controller):

    @http.route(
        ["/sms/infobip/inbound"],
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def receive_mo(self, **kwargs):
        try:
            content_type = request.httprequest.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raw = request.httprequest.data.decode("utf-8") or "{}"
                payload = json.loads(raw)
            else:
                # Form-encoded callbacks are rare for Infobip but supported.
                payload = dict(kwargs)

            messages = self._extract_messages(payload)
            if not messages:
                _logger.info("Infobip MO webhook received with no extractable messages")
                return self._ok_response()

            ChatbotMessage = request.env["whatsapp.chatbot.message"].sudo()
            for msg in messages:
                from_number = msg.get("from") or msg.get("sender") or ""
                # Infobip prefers cleanText (decoded UTF-8 payload) over the
                # raw text but either is acceptable.
                body = msg.get("cleanText") or msg.get("text") or ""
                infobip_id = msg.get("messageId") or msg.get("id")
                _logger.info(
                    f"Infobip MO from={from_number!r} body={body[:120]!r} id={infobip_id}"
                )
                try:
                    ChatbotMessage.process_incoming_sms_message(
                        from_number=from_number,
                        message_text=body,
                        sms_message_id=infobip_id,
                    )
                except Exception as inner:
                    # One malformed message shouldn't drop the rest of the batch.
                    _logger.error(
                        f"Failed processing inbound SMS from {from_number}: {inner}",
                        exc_info=True,
                    )

            return self._ok_response()
        except Exception as e:
            _logger.error(f"Error in Infobip MO webhook: {e}", exc_info=True)
            return self._ok_response()  # Always 200 — Infobip retries on non-2xx

    @staticmethod
    def _extract_messages(payload):
        """Accept either the envelope shape ({results: [...]}) or a single
        message object. Returns a list of dicts."""
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        if "results" in payload and isinstance(payload["results"], list):
            return payload["results"]
        # Single-message shape — heuristically detect by presence of from+text.
        if "from" in payload and ("text" in payload or "cleanText" in payload):
            return [payload]
        return []

    @staticmethod
    def _ok_response():
        return request.make_response(
            json.dumps({"status": "ok"}),
            headers=[("Content-Type", "application/json")],
        )
