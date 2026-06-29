# -*- coding: utf-8 -*-
"""Agent Workspace endpoints — backs the OWL client action that agents use
during live voice calls.

Endpoints (all type='json', auth='user' — only authenticated agents reach them):
    /voice/start        Create a call session against a chatbot + contact
    /voice/turn         Advance the engine (agent typed / clicked something)
    /voice/update       Apply slot edits without advancing
    /voice/end          Close the session with an outcome + wrap-up notes
    /voice/setup        Return the chatbot's slot definitions for the right pane
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AgentWorkspaceController(http.Controller):

    @http.route("/voice/start", type="json", auth="user", methods=["POST"], csrf=False)
    def start(self, chatbot_id=None, contact_details=None, **_kw):
        """Create or reuse a contact + open a new call session."""
        if not chatbot_id:
            return {"error": "Missing chatbot_id"}
        try:
            details = contact_details or {}
            mobile = (details.get('mobile') or '').strip()
            name = (details.get('name') or '').strip()
            if not mobile:
                return {"error": "Customer mobile is required to start a call."}

            Partner = request.env['res.partner'].sudo()
            partner = Partner.search([('mobile', '=', mobile)], limit=1)
            if not partner:
                partner = Partner.create({
                    'name': name or f"Caller {mobile}",
                    'mobile': mobile,
                    'is_company': False,
                })
            elif name and partner.name != name:
                # Don't relabel existing real partners — just leave their name as-is.
                pass

            Contact = request.env['whatsapp.chatbot.contact'].sudo()
            contact = Contact.search([('partner_id', '=', partner.id)], limit=1)
            if not contact:
                contact = Contact.create({
                    'partner_id': partner.id,
                })

            Session = request.env['comm.voice.call.session'].sudo()
            session = Session.create({
                'chatbot_id': int(chatbot_id),
                'contact_id': contact.id,
                'agent_id': request.env.user.id,
            })
            return {
                "session_id": session.id,
                "contact_id": contact.id,
                "partner": {
                    "id": partner.id, "name": partner.name, "mobile": partner.mobile,
                    "email": partner.email or '',
                },
            }
        except Exception as e:
            _logger.error("Workspace start failed: %s", e, exc_info=True)
            return {"error": str(e)}

    @http.route("/voice/turn", type="json", auth="user", methods=["POST"], csrf=False)
    def turn(self, session_id=None, user_input=None, initial_variables=None, **_kw):
        if not session_id:
            return {"error": "Missing session_id"}
        try:
            return request.env["whatsapp.chatbot.message"].sudo().agent_turn(
                call_session_id=int(session_id),
                user_input=user_input,
                initial_variables=initial_variables,
            )
        except Exception as e:
            _logger.error("Workspace turn failed: %s", e, exc_info=True)
            return {"error": str(e)}

    @http.route("/voice/update", type="json", auth="user", methods=["POST"], csrf=False)
    def update(self, session_id=None, initial_variables=None, **_kw):
        if not session_id:
            return {"error": "Missing session_id"}
        try:
            return request.env["whatsapp.chatbot.message"].sudo().agent_update_state(
                call_session_id=int(session_id),
                initial_variables=initial_variables,
            )
        except Exception as e:
            _logger.error("Workspace update failed: %s", e, exc_info=True)
            return {"error": str(e)}

    @http.route("/voice/end", type="json", auth="user", methods=["POST"], csrf=False)
    def end(self, session_id=None, outcome='resolved', notes=None, **_kw):
        if not session_id:
            return {"error": "Missing session_id"}
        try:
            sess = request.env["comm.voice.call.session"].sudo().browse(int(session_id)).exists()
            if not sess:
                return {"error": "Session not found"}
            sess.action_close(outcome=outcome, notes=notes)
            return {"ok": True, "outcome": sess.outcome, "duration": sess.duration_seconds}
        except Exception as e:
            _logger.error("Workspace end failed: %s", e, exc_info=True)
            return {"error": str(e)}

    @http.route("/voice/setup", type="json", auth="user", methods=["POST"], csrf=False)
    def setup(self, chatbot_id=None, contact_id=None, **_kw):
        """Return slot definitions (variables) for the chatbot + linked bots,
        with the contact's saved values prefilled. Mirrors the simulator's
        /chatbot/simulate/setup so the right-pane dashboard can render."""
        if not chatbot_id:
            return {"bots": []}
        try:
            data = request.env["whatsapp.chatbot.message"].sudo().simulator_setup(
                chatbot_id=int(chatbot_id),
                contact_details={},  # we look up by contact below
            )
            if contact_id:
                contact = request.env["whatsapp.chatbot.contact"].sudo().browse(int(contact_id)).exists()
                if contact:
                    saved = {v.variable_id.id: (v.value or '')
                             for v in contact.variable_value_ids
                             if v.variable_id}
                    for bot in data.get('bots', []):
                        for v in bot.get('variables', []):
                            v['value'] = saved.get(v['id'], v.get('value', ''))
                    # also expose pivot_text per variable so the workspace can
                    # render it as a tooltip hint.
                    Variable = request.env['whatsapp.chatbot.variable'].sudo()
                    for bot in data.get('bots', []):
                        for v in bot.get('variables', []):
                            rec = Variable.browse(v['id']).exists()
                            if rec:
                                v['pivot_text'] = rec.pivot_text or ''
            return data
        except Exception as e:
            _logger.error("Workspace setup failed: %s", e, exc_info=True)
            return {"bots": []}
