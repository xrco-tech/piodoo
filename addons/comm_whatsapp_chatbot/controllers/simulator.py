# -*- coding: utf-8 -*-
"""Flow simulator endpoint.

Used by the OWL flow-builder right-panel simulator. Runs a turn of the
chatbot's flow against the REAL engine — every variable / jump /
execute_code path that production traffic exercises is exercised here
too. Records are persisted with is_simulator=True so analytics queries
filter them out; outbound WA / SMS sends are short-circuited via the
env context so no real APIs are called.

Auth=user so it can't be hit from outside the Odoo session.
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ChatbotSimulatorController(http.Controller):

    @http.route(
        "/chatbot/simulate",
        type="json", auth="user", methods=["POST"], csrf=False,
    )
    def simulate(self, chatbot_id=None, session_state=None, user_input=None,
                 contact_details=None, initial_variables=None, **_kw):
        if not chatbot_id:
            return {
                "session_state": None,
                "bubbles": [{"text": "Missing chatbot_id", "step_type": "error"}],
                "terminate": True,
                "channel": "whatsapp",
                "wait_for_input": False,
            }
        try:
            result = request.env["whatsapp.chatbot.message"].sudo().simulate_turn(
                chatbot_id=int(chatbot_id),
                session_state=session_state,
                user_input=user_input,
                contact_details=contact_details,
                initial_variables=initial_variables,
            )
            return result
        except Exception as e:
            _logger.error("Simulator failed: %s", e, exc_info=True)
            return {
                "session_state": None,
                "bubbles": [{"text": "Simulator error.", "step_type": "error"}],
                "terminate": True,
                "channel": "whatsapp",
                "wait_for_input": False,
            }

    @http.route(
        "/chatbot/simulate/setup",
        type="json", auth="user", methods=["POST"], csrf=False,
    )
    def setup(self, chatbot_id=None, contact_details=None, **_kw):
        """Returns persona defaults + variable groups (root bot + every
        chatbot reachable via jump_to_flow) so the frontend can render
        editable inputs before / during a session."""
        if not chatbot_id:
            return {"persona": {}, "bots": []}
        try:
            return request.env["whatsapp.chatbot.message"].sudo().simulator_setup(
                chatbot_id=int(chatbot_id),
                contact_details=contact_details,
            )
        except Exception as e:
            _logger.error("Simulator setup failed: %s", e, exc_info=True)
            return {"persona": {}, "bots": []}

    @http.route(
        "/chatbot/simulate/update",
        type="json", auth="user", methods=["POST"], csrf=False,
    )
    def update_state(self, chatbot_id=None, session_state=None,
                     contact_details=None, initial_variables=None, **_kw):
        """Apply persona + variable edits to a RUNNING simulator session
        without advancing the flow. Used by the in-session inline editor."""
        if not chatbot_id:
            return {"session_state": None}
        try:
            return request.env["whatsapp.chatbot.message"].sudo().simulator_update_state(
                chatbot_id=int(chatbot_id),
                session_state=session_state,
                contact_details=contact_details,
                initial_variables=initial_variables,
            )
        except Exception as e:
            _logger.error("Simulator update_state failed: %s", e, exc_info=True)
            return {"session_state": session_state}
