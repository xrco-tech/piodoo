# -*- coding: utf-8 -*-
"""Flow simulator endpoint.

Used by the OWL flow-builder right-panel simulator. Runs a turn of the
chatbot's flow against an ephemeral in-memory session and returns the
outgoing bubbles + updated session state. Never writes to the database.

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
    def simulate(self, chatbot_id=None, session_state=None, user_input=None, **_kw):
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
