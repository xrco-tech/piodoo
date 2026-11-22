# -*- coding: utf-8 -*-
"""Send the sessions of a USSD code that is connected to a flow to that flow.

Every gateway (Africa's Talking, Connect Mobile) ends up in `_ussd_reply`. A
code whose account is connected to a flow is answered here; every other code
goes on to whatever answered it before, untouched.
"""
from odoo.http import request

from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController


class FlowUssdController(UssdController):

    @staticmethod
    def _flow_session(session_id):
        return request.env['comm.bot.ussd.session'].sudo().search(
            [('session_id', '=', session_id)], limit=1)

    def _ussd_reply(self, session_id, service_code, phone_number, text, latest_input=None):
        Session = request.env['comm.bot.ussd.session'].sudo()
        live = Session.search([('session_id', '=', session_id),
                               ('outcome', '=', 'open')], limit=1)
        account = request.env['comm.ussd.account'].sudo().find_for_service_code(service_code)
        if not live and not account.flow_bot_id:
            return super()._ussd_reply(session_id, service_code, phone_number, text, latest_input)
        if latest_input is None:
            latest_input = self._latest_input(text)
        return Session.ussd_handle(session_id, service_code, phone_number, text, latest_input)

    def _ussd_closed(self, session_id, status, seconds=None):
        request.env['comm.bot.ussd.session'].sudo().ussd_closed(session_id, status, seconds=seconds)
        return super()._ussd_closed(session_id, status, seconds)

    def _ussd_session_service_code(self, session_id):
        return self._flow_session(session_id).service_code or \
            super()._ussd_session_service_code(session_id)
