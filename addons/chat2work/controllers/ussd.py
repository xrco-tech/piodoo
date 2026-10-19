# -*- coding: utf-8 -*-
"""Dispatch Chat2Work service codes to the coded flow.

Service codes whose comm.ussd.account has flow_engine='chat2work' bypass the
chatbot step engine entirely — notably its inbound path, which creates a
res.partner for every dialler before any consent is given.
"""

from odoo import http
from odoo.http import request

from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController


class Chat2workUssdController(UssdController):

    @http.route()
    def receive_ussd(self, **kwargs):
        params = self._extract_params(kwargs)
        service_code = (params.get("serviceCode") or params.get("service_code") or "").strip()
        account = request.env["comm.ussd.account"].sudo().find_for_service_code(service_code)
        if not account or account.flow_engine != "chat2work":
            return super().receive_ussd(**kwargs)
        session_id = params.get("sessionId") or params.get("session_id") or ""
        phone_number = (params.get("phoneNumber") or params.get("phone_number") or "").strip()
        if not session_id or not phone_number:
            return self._text_response("END Service unavailable. Please try again later.")
        text = params.get("text") or ""
        body = request.env["chat2work.ussd.session"].sudo().ussd_handle(
            session_id, service_code, phone_number, text, self._latest_input(text),
        )
        return self._text_response(body)

    @http.route()
    def ussd_notifications(self, **kwargs):
        params = self._extract_params(kwargs)
        session_id = params.get("sessionId") or params.get("session_id") or ""
        if session_id:
            request.env["chat2work.ussd.session"].sudo().ussd_session_closed(session_id)
        return super().ussd_notifications(**kwargs)
