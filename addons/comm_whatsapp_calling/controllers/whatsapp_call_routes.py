# -*- coding: utf-8 -*-

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappCallRoutes(http.Controller):
    """JSON routes for the UI to answer/decline/end WhatsApp calls."""

    @http.route("/whatsapp/call/bus_channel", type="json", auth="user")
    def bus_channel(self, **kwargs):
        """Return db and uid so the frontend can subscribe to the incoming-call bus channel."""
        return {"db": request.db, "uid": request.session.uid}

    @http.route(
        "/whatsapp/call/answer/<int:call_log_id>",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def answer_call(self, call_log_id, sdp_answer=None, **kwargs):
        call_log = request.env["whatsapp.call.log"].sudo().browse(call_log_id)
        if not call_log.exists():
            return {"success": False, "error": "Call not found"}
        if call_log.action_accept(sdp_answer=sdp_answer):
            return {"success": True}
        return {"success": False, "error": "Accept failed"}

    @http.route(
        "/whatsapp/call/decline/<int:call_log_id>",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def decline_call(self, call_log_id, **kwargs):
        call_log = request.env["whatsapp.call.log"].sudo().browse(call_log_id)
        if not call_log.exists():
            return {"success": False, "error": "Call not found"}
        if call_log.action_decline():
            return {"success": True}
        return {"success": False, "error": "Decline failed"}
