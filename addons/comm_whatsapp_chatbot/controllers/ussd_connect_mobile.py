# -*- coding: utf-8 -*-
"""Connect Mobile USSD application endpoint.

https://docs.connect-mobile.co.za/api/ussd/ussd-app-api

The gateway calls this URL once per screen, as GET, form POST, JSON or XML
(chosen when Connect Mobile provisions the code). Fields:

    msisdn     — dialler, e.g. 27823456789
    sessionid  — opaque; the network may reuse it for a later session
    request    — the full dialled code on the first request (e.g.
                 *120*12345#), afterwards only the subscriber's latest input
    type       — 1 initial, 2 subscriber response, 3 ended by subscriber or
                 network, 4 timed out
    mno        — lowercase network name (vodacom, mtn, cell c, telkom)

The response, in the request's format, has `text` and `session` (1 keeps the
session open, 0 ends it). The gateway drops the session if we take longer
than five seconds.

The callback carries no credentials, so the URL holds the USSD account's
?token=, which also tells us which account (and so which bot) was dialled.
"""

import json
import logging
from urllib.parse import urlencode

from lxml import etree

from odoo import http
from odoo.http import request, Response

from .ussd_inbound import UssdController

_logger = logging.getLogger(__name__)

TYPE_INITIAL = 1
TYPE_RESPONSE = 2
TYPE_ENDED = 3
TYPE_TIMEOUT = 4

# Session ids are namespaced so they can't collide with other gateways' ids
SESSION_PREFIX = 'cm:'


class ConnectMobileUssdController(http.Controller):

    @http.route(['/ussd/connectmobile'], type="http", auth="public",
                methods=['GET', 'POST'], csrf=False)
    def connect_mobile_ussd(self, **kwargs):
        fmt, params = self._parse_request(kwargs)
        account = request.env['comm.ussd.account'].sudo().find_for_webhook_token(
            'connect_mobile', request.httprequest.args.get('token'))
        if not account:
            _logger.warning("Connect Mobile USSD called with missing or unknown token")
            return Response("Forbidden", status=403)

        try:
            sid = (params.get('sessionid') or '').strip()
            msisdn = (params.get('msisdn') or '').strip()
            req_text = params.get('request') or ''
            try:
                req_type = int(params.get('type') or 0)
            except (TypeError, ValueError):
                req_type = 0
            _logger.info("Connect Mobile USSD session=%r from=%r type=%s request=%r",
                         sid, msisdn, req_type, req_text)
            if not sid or not msisdn:
                return self._respond(fmt, "Service unavailable.", end=True)

            Session = request.env['whatsapp.chatbot.ussd.session'].sudo()
            session_key = SESSION_PREFIX + sid
            existing = Session.search([('session_id', '=', session_key)], limit=1)

            if req_type in (TYPE_ENDED, TYPE_TIMEOUT):
                if existing and existing.outcome == 'open':
                    existing.outcome = 'hangup' if req_type == TYPE_ENDED else 'timeout'
                return self._respond(fmt, "", end=True)

            ChatbotMessage = request.env['whatsapp.chatbot.message'].sudo()
            if existing and existing.outcome == 'open' and req_type != TYPE_INITIAL:
                existing.breadcrumb = '*'.join(filter(None, [existing.breadcrumb, req_text]))
                body, terminate = ChatbotMessage.render_ussd_session(existing, req_text)
                return self._respond(fmt, body, end=terminate)

            if req_type == TYPE_RESPONSE:
                # A reply for a session we don't have open (finished, or lost).
                return self._respond(fmt, "Session expired. Please dial again.", end=True)

            if existing:
                # The network reused this session id: retire the old row so
                # the new session can take the id.
                vals = {'session_id': f"{session_key}:{existing.id}"}
                if existing.outcome == 'open':
                    vals['outcome'] = 'timeout'
                existing.write(vals)

            chatbot = UssdController._resolve_ussd_chatbot_for_account(account)
            if not chatbot:
                _logger.warning("No USSD chatbot configured for account %s", account.name)
                return self._respond(fmt, "Service unavailable.", end=True)

            session = UssdController._start_session(
                session_key, params.get('dialstring') or req_text or account.service_code,
                msisdn, chatbot,
                ussd_account_id=account.id,
                carrier=(params.get('mno') or '').strip().lower() or False,
            )
            body, terminate = ChatbotMessage.render_ussd_session(session, user_input=None)
            return self._respond(fmt, body, end=terminate)

        except Exception as e:
            _logger.error("Connect Mobile USSD error: %s", e, exc_info=True)
            return self._respond(fmt, "Service error.", end=True)

    # ── Request / response formats ───────────────────────────────────────────

    @staticmethod
    def _parse_request(kwargs):
        """(format, params) where format is 'form', 'json' or 'xml'."""
        content_type = request.httprequest.headers.get('Content-Type', '')
        params = dict(kwargs)
        params.pop('token', None)
        if 'json' in content_type:
            try:
                data = json.loads(request.httprequest.get_data(as_text=True) or '{}')
            except ValueError:
                data = {}
            return 'json', {k: v for k, v in data.items() if v is not None} if isinstance(data, dict) else {}
        if 'xml' in content_type:
            return 'xml', ConnectMobileUssdController._parse_xml(request.httprequest.get_data())
        return 'form', params

    @staticmethod
    def _parse_xml(raw):
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            root = etree.fromstring(raw or b'', parser=parser)
        except etree.XMLSyntaxError:
            return {}
        params = {}
        for name in ('msisdn', 'sessionid', 'network', 'request', 'menu', 'option', 'mno', 'dialstring'):
            node = root.find(f'.//{name}')
            if node is not None:
                params[name] = node.text or ''
        node = root.find('.//request')
        if node is not None and node.get('type'):
            params['type'] = node.get('type')
        return params

    @staticmethod
    def _respond(fmt, text, end):
        session = 0 if end else 1
        if fmt == 'json':
            return request.make_response(
                json.dumps({'text': text, 'session': session}),
                headers=[('Content-Type', 'application/json')])
        if fmt == 'xml':
            root = etree.Element('ussd')
            etree.SubElement(root, 'text').text = text
            etree.SubElement(root, 'session').text = str(session)
            return request.make_response(
                etree.tostring(root, xml_declaration=True, encoding='UTF-8'),
                headers=[('Content-Type', 'application/xml; charset=utf-8')])
        return request.make_response(
            urlencode({'text': text, 'session': session}),
            headers=[('Content-Type', 'application/x-www-form-urlencoded; charset=utf-8')])
