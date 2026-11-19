# -*- coding: utf-8 -*-
"""USSD inbound + notifications endpoints.

Generic shape — designed to fit Africa's Talking, but every USSD gateway uses
similar fields:

    sessionId    — opaque session token (e.g. ATUid_xxx)
    serviceCode  — the dialled USSD code (e.g. *123#) — used to route to a
                   chatbot by sender_address
    phoneNumber  — the dialler's MSISDN
    text         — the accumulated breadcrumb of all keypresses, separated
                   by `*`. Empty string on first turn. The latest keypress
                   is the last segment.

Response shape is plain text, always prefixed with either:

    CON <body>  — keep the session open and show <body>
    END <body>  — terminate the session and show <body>

Notifications endpoint receives session-end events (timeout, hangup,
completion) — we update the session record's outcome and return 200.

Connect Mobile speaks a different shape on its own address, /ussd/connectmobile
(see the section below). Both gateways end up in the same `_ussd_reply`, so a
flow behaves the same whichever one the caller dialled through.
"""

import json
import logging
from urllib.parse import urlencode

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class UssdController(http.Controller):

    @http.route(
        ["/ussd/inbound"],
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def receive_ussd(self, **kwargs):
        params = self._extract_params(kwargs)
        session_id = params.get("sessionId") or params.get("session_id") or ""
        service_code = (params.get("serviceCode") or params.get("service_code") or "").strip()
        phone_number = (params.get("phoneNumber") or params.get("phone_number") or "").strip()
        text = params.get("text") or ""
        if not session_id or not phone_number:
            _logger.warning(f"USSD inbound missing sessionId or phoneNumber: {params}")
            return self._text_response("END Service unavailable.")
        return self._text_response(self._ussd_reply(session_id, service_code, phone_number, text))

    def _ussd_reply(self, session_id, service_code, phone_number, text, latest_input=None):
        """One turn of a session, whatever gateway it came through: the screen
        to show, as 'CON …' (keep the session open) or 'END …' (close it).

        `text` is everything typed so far, joined by `*`; `latest_input` is the
        last thing typed, worked out from `text` when the gateway does not
        send it on its own."""
        try:
            _logger.info(
                f"USSD inbound session={session_id!r} svc={service_code!r} "
                f"from={phone_number!r} text={text!r}"
            )

            ChatbotMessage = request.env["whatsapp.chatbot.message"].sudo()
            Session = request.env["whatsapp.chatbot.ussd.session"].sudo()
            existing_session = Session.search(
                [("session_id", "=", session_id)], limit=1,
            )

            if existing_session:
                user_input = self._latest_input(text) if latest_input is None else latest_input
                existing_session.breadcrumb = text
                body, terminate = ChatbotMessage.render_ussd_session(existing_session, user_input)
                return self._format_ussd(body, terminate)

            # First turn — route by service_code → chatbot, create session.
            chatbot = self._resolve_ussd_chatbot(service_code)
            if not chatbot:
                _logger.warning(f"No USSD chatbot configured for service_code={service_code!r}")
                return "END Service unavailable."

            partner = ChatbotMessage._find_or_create_partner(
                phone_number, {"wa_id": phone_number, "profile": {}},
            )
            ChatbotContact = request.env["whatsapp.chatbot.contact"].sudo()
            contact = ChatbotContact.search([("partner_id", "=", partner.id)], limit=1)
            if not contact:
                contact = ChatbotContact.create({"partner_id": partner.id})

            # Treat session start like a trigger restart: clear contact's
            # variable values and call stack so the flow runs from a clean slate.
            contact.variable_value_ids.unlink()
            contact.write({
                "last_chatbot_id": chatbot.id,
                "last_step_id": False,
                "call_stack": [],
            })
            ChatbotMessage._mark_contact_entered(contact, chatbot)

            session = Session.find_or_create_for_inbound(
                session_id=session_id,
                service_code=service_code,
                phone_number=phone_number,
                chatbot=chatbot,
                contact=contact,
            )
            session.breadcrumb = text
            body, terminate = ChatbotMessage.render_ussd_session(session, user_input=None)
            return self._format_ussd(body, terminate)

        except Exception as e:
            _logger.error(f"USSD inbound error: {e}", exc_info=True)
            return "END Service error."

    def _ussd_closed(self, session_id, status, seconds=None):
        """The gateway says a session is over: `status` is 'timeout', 'hangup'
        or 'completed'; `seconds` is its own figure for the length, if any."""
        session = request.env["whatsapp.chatbot.ussd.session"].sudo().search(
            [("session_id", "=", session_id)], limit=1)
        if not session:
            return
        if seconds:
            session = session.with_context(ussd_seconds=seconds)
        if status in ("timeout", "hangup", "completed"):
            session.outcome = status

    # ── Connect Mobile ───────────────────────────────────────────────────────
    #
    # Connect Mobile calls one address for everything, by GET, form POST or
    # JSON, with:
    #     msisdn     — the caller, international format without the plus
    #     sessionid  — the network's session number (it can come round again)
    #     request    — the dialled code on the first request, then what the
    #                  caller typed (only the latest entry, not the whole trail)
    #     type       — 1 first request, 2 caller's answer, 3 ended by the
    #                  caller or network, 4 timed out
    #     dialstring — the code that started the session
    #     mno        — the caller's network, in lower case
    # and expects `text` plus `session` (1 keep open, 0 close) back, in the
    # format it called with. It allows five seconds for the answer.

    @http.route(
        ["/ussd/connectmobile"],
        type="http", auth="public", methods=["GET", "POST"], csrf=False,
    )
    def receive_ussd_connect_mobile(self, **kwargs):
        as_json = "application/json" in request.httprequest.headers.get("Content-Type", "")
        try:
            params = self._extract_params(kwargs)
            msisdn = str(params.get("msisdn") or "").strip().lstrip("+")
            network_session = str(params.get("sessionid") or "").strip()
            typed = str(params.get("request") or "").strip()
            try:
                kind = int(params.get("type") or 0)
            except (TypeError, ValueError):
                kind = 0
            if not msisdn or not network_session or kind not in (1, 2, 3, 4):
                _logger.warning("Connect Mobile USSD request not understood: %s", params)
                return self._connect_mobile_response("END Service unavailable.", as_json)

            Held = request.env["comm.ussd.gateway.session"].sudo()
            key = "%s/%s" % (network_session, msisdn)
            held = Held.search([("provider", "=", "connect_mobile"), ("key", "=", key)], limit=1)

            if kind in (3, 4):
                if held:
                    self._ussd_closed(held.session_id, "hangup" if kind == 3 else "timeout")
                    held.unlink()
                return self._connect_mobile_response("END ", as_json)

            if kind == 1:
                if held:
                    # The network reused the number before telling us the last session ended.
                    self._ussd_closed(held.session_id, "hangup")
                    held.unlink()
                service_code = str(params.get("dialstring") or typed).strip()
                account = request.env["comm.ussd.account"].sudo().find_for_service_code(service_code)
                if not account or account.provider != "connect_mobile":
                    _logger.warning("Connect Mobile USSD: no Connect Mobile account for %r", service_code)
                    return self._connect_mobile_response("END Service unavailable.", as_json)
                held = Held.create({
                    "provider": "connect_mobile", "key": key, "service_code": service_code,
                    "network": str(params.get("mno") or "").strip() or False,
                })
                reply = self._ussd_reply(held.session_id, service_code, "+" + msisdn, "", "")
            else:
                if not held:
                    _logger.info("Connect Mobile USSD: answer for a session we no longer hold (%s)", key)
                    return self._connect_mobile_response(
                        "END Your session has ended. Please dial again.", as_json)
                held.breadcrumb = "%s*%s" % (held.breadcrumb, typed) if held.turns else typed
                held.turns += 1
                reply = self._ussd_reply(held.session_id, held.service_code, "+" + msisdn,
                                         held.breadcrumb or "*", typed)
            if not reply.startswith("CON"):
                held.unlink()
            return self._connect_mobile_response(reply, as_json)
        except Exception:
            _logger.exception("Connect Mobile USSD error")
            return self._connect_mobile_response("END Service error.", as_json)

    @staticmethod
    def _connect_mobile_response(reply, as_json):
        """Turn 'CON …' / 'END …' into Connect Mobile's text + session answer."""
        payload = {"text": reply[4:].strip(), "session": 1 if reply.startswith("CON") else 0}
        if as_json:
            return request.make_response(
                json.dumps(payload), headers=[("Content-Type", "application/json")])
        return request.make_response(
            urlencode(payload), headers=[("Content-Type", "application/x-www-form-urlencoded")])

    @staticmethod
    def _duration_seconds(params):
        """The session length the gateway reports, in seconds, or None."""
        try:
            millis = float(params.get("durationInMillis") or 0)
        except (TypeError, ValueError):
            return None
        return millis / 1000.0 if millis > 0 else None

    @http.route(
        ["/ussd/notifications"],
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def ussd_notifications(self, **kwargs):
        """Session-end events: completion / timeout / user hangup.
        We update the session's outcome and return 200."""
        try:
            params = self._extract_params(kwargs)
            session_id = params.get("sessionId") or params.get("session_id") or ""
            status = (params.get("status") or params.get("event") or "").lower()
            _logger.info(f"USSD notification session={session_id!r} status={status!r}")
            if session_id:
                if status in ("timeout", "expired"):
                    outcome = "timeout"
                elif status in ("hangup", "user_hangup", "cancelled"):
                    outcome = "hangup"
                elif status in ("completed", "success"):
                    outcome = "completed"
                else:
                    outcome = status
                self._ussd_closed(session_id, outcome, self._duration_seconds(params))
            return request.make_response(
                json.dumps({"status": "ok"}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.error(f"USSD notifications error: {e}", exc_info=True)
            return request.make_response(
                json.dumps({"status": "ok"}),
                headers=[("Content-Type", "application/json")],
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_params(kwargs):
        """Accept either form-encoded fields (kwargs) or JSON body."""
        content_type = request.httprequest.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                raw = request.httprequest.data.decode("utf-8") or "{}"
                return json.loads(raw)
            except Exception:
                return {}
        return dict(kwargs)

    @staticmethod
    def _latest_input(text):
        """The carrier sends the entire breadcrumb on each turn. The user's
        latest keypress is the last `*`-separated segment, or '' on first turn."""
        if not text:
            return ''
        parts = text.split('*')
        return parts[-1] if parts else ''

    @staticmethod
    def _resolve_ussd_chatbot(service_code):
        """Resolve a USSD chatbot for the dialled service code.

        Routing order:
          1. Find the comm.ussd.account whose service_code matches; pick the
             first published bot wired to that account.
          2. If no account matches, fall back to a published USSD bot with no
             account configured (the install-wide catch-all).
        """
        Bot = request.env["whatsapp.chatbot"].sudo()
        Account = request.env["comm.ussd.account"].sudo()
        if service_code:
            account = Account.find_for_service_code(service_code)
            if account:
                specific = Bot.search([
                    ("channel", "=", "ussd"),
                    ("ussd_account_id", "=", account.id),
                    ("status", "=", "published"),
                ], limit=1)
                if specific:
                    return specific
        return Bot.search([
            ("channel", "=", "ussd"),
            ("status", "=", "published"),
            ("ussd_account_id", "=", False),
        ], limit=1)

    @staticmethod
    def _format_ussd(body, terminate):
        prefix = "END" if terminate else "CON"
        return f"{prefix} {body}".strip()

    @staticmethod
    def _text_response(body):
        return request.make_response(
            body,
            headers=[("Content-Type", "text/plain; charset=utf-8")],
        )
