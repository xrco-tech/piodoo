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
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class UssdController(http.Controller):

    @http.route(
        ["/ussd/inbound"],
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def receive_ussd(self, **kwargs):
        try:
            params = self._extract_params(kwargs)
            session_id = params.get("sessionId") or params.get("session_id") or ""
            service_code = (params.get("serviceCode") or params.get("service_code") or "").strip()
            phone_number = (params.get("phoneNumber") or params.get("phone_number") or "").strip()
            text = params.get("text") or ""

            if not session_id or not phone_number:
                _logger.warning(f"USSD inbound missing sessionId or phoneNumber: {params}")
                return self._text_response("END Service unavailable.")

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
                # Continuing turn: parse latest keypress out of the breadcrumb.
                user_input = self._latest_input(text)
                existing_session.breadcrumb = text
                body, terminate = ChatbotMessage.render_ussd_session(existing_session, user_input)
                return self._text_response(self._format_ussd(body, terminate))

            # First turn — route by service_code → chatbot, create session.
            chatbot = self._resolve_ussd_chatbot(service_code)
            if not chatbot:
                _logger.warning(f"No USSD chatbot configured for service_code={service_code!r}")
                return self._text_response("END Service unavailable.")

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
            return self._text_response(self._format_ussd(body, terminate))

        except Exception as e:
            _logger.error(f"USSD inbound error: {e}", exc_info=True)
            return self._text_response("END Service error.")

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
                Session = request.env["whatsapp.chatbot.ussd.session"].sudo()
                session = Session.search([("session_id", "=", session_id)], limit=1)
                if session:
                    if status in ("timeout", "expired"):
                        session.outcome = "timeout"
                    elif status in ("hangup", "user_hangup", "cancelled"):
                        session.outcome = "hangup"
                    elif status in ("completed", "success"):
                        session.outcome = "completed"
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
