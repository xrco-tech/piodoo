# -*- coding: utf-8 -*-
"""Dispatch Chat2Work service codes to the coded flow.

Service codes whose comm.ussd.account has flow_engine='chat2work' bypass the
chatbot step engine entirely — notably its inbound path, which creates a
res.partner for every dialler before any consent is given. This holds for
every gateway (Africa's Talking, Connect Mobile): they all reach `_ussd_reply`.
"""

from odoo.http import request

from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController


class Chat2workUssdController(UssdController):

    def _ussd_reply(self, session_id, service_code, phone_number, text, latest_input=None):
        account = request.env["comm.ussd.account"].sudo().find_for_service_code(service_code)
        if not account or account.flow_engine != "chat2work":
            return super()._ussd_reply(session_id, service_code, phone_number, text, latest_input)
        if latest_input is None:
            latest_input = self._latest_input(text)
        return request.env["chat2work.ussd.session"].sudo().ussd_handle(
            session_id, service_code, phone_number, text, latest_input)

    def _ussd_closed(self, session_id, status, seconds=None):
        request.env["chat2work.ussd.session"].sudo().ussd_session_closed(session_id, seconds=seconds)
        return super()._ussd_closed(session_id, status, seconds)
