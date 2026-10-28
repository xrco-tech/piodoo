# -*- coding: utf-8 -*-
"""Inbound SMS (MO) webhooks for Infobip, Africa's Talking and Connect Mobile.

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
from odoo.http import request, Response
from odoo.addons.comm_sms.controllers.main import _forbidden, _webhook_account

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
                to_number = msg.get("to") or msg.get("destination") or ""
                # Infobip prefers cleanText (decoded UTF-8 payload) over the
                # raw text but either is acceptable.
                body = msg.get("cleanText") or msg.get("text") or ""
                infobip_id = msg.get("messageId") or msg.get("id")
                _logger.info(
                    f"Infobip MO from={from_number!r} to={to_number!r} body={body[:120]!r} id={infobip_id}"
                )
                try:
                    ChatbotMessage.process_incoming_sms_message(
                        from_number=from_number,
                        message_text=body,
                        sms_message_id=infobip_id,
                        to_number=to_number,
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


def _dispatch_inbound(provider, account, from_number, body, message_id):
    """Hand one inbound SMS to the chatbot. The token-matched account's sender
    ID is the canonical `to`, so bot routing doesn't depend on how each
    provider formats the destination address."""
    _logger.info(
        f"{provider} MO from={from_number!r} to={account.sender_id!r} body={(body or '')[:120]!r} id={message_id}"
    )
    try:
        request.env["whatsapp.chatbot.message"].sudo().process_incoming_sms_message(
            from_number=from_number,
            message_text=body,
            sms_message_id=message_id,
            to_number=account.sender_id,
        )
    except Exception as e:
        _logger.error(f"Failed processing inbound {provider} SMS from {from_number}: {e}", exc_info=True)


class AfricasTalkingMOController(http.Controller):

    @http.route(
        ["/sms/africastalking/inbound"],
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def receive_mo(self, **kwargs):
        """Form-encoded: from, to, text, date, id, linkId, networkCode."""
        account = _webhook_account("africastalking")
        if not account:
            return _forbidden()
        if kwargs.get("from"):
            _dispatch_inbound("Africa's Talking", account, kwargs["from"],
                              kwargs.get("text") or "", kwargs.get("id"))
        return Response("OK", status=200)


class ConnectMobileMOController(http.Controller):

    @http.route(
        ["/sms/connectmobile/inbound"],
        type="http", auth="public", methods=["GET", "POST"], csrf=False,
    )
    def receive_mo(self, **kwargs):
        """Query parameters: oa (sender), da (our number), ud (text), sms_id,
        userid, timestamp, charset."""
        account = _webhook_account("connect_mobile")
        if not account:
            return _forbidden()
        if kwargs.get("oa"):
            _dispatch_inbound("Connect Mobile", account, kwargs["oa"],
                              kwargs.get("ud") or "", kwargs.get("sms_id"))
        return Response("OK", status=200)
