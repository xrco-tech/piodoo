# -*- coding: utf-8 -*-

import logging
from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappCallRoutes(http.Controller):
    """JSON routes for the UI to answer/decline/end WhatsApp calls."""

    @http.route("/whatsapp/call/bus_channel", type="json", auth="user")
    def bus_channel(self, **kwargs):
        """Return db and uid so the frontend can subscribe to the incoming-call bus channel."""
        return {"db": request.db, "uid": request.session.uid}

    @http.route(
        "/whatsapp/call/dial",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def dial_call(self, to_number=None, sdp_offer=None,
                  account_id=None, partner_id=None,
                  chatbot_id=None, **kwargs):
        """Initiate an outbound call. The browser has already produced
        an SDP offer via RTCPeerConnection; we relay it to Meta.

        Returns {success: True, call_log_id, meta_call_id} on success;
        {success: False, error} on any failure.
        """
        if not to_number or not sdp_offer:
            return {"success": False,
                    "error": "to_number and sdp_offer are required."}

        # Pick the WABA account: explicit account_id → argument, else the
        # single-active default. Owns the credentials + phone_number_id
        # used as the caller identity.
        Account = request.env["comm.whatsapp.account"].sudo()
        acc = Account.browse(account_id) if account_id else Account
        if not acc.exists():
            acc = Account.get_default()
        if not acc.exists() or not acc.phone_number_id or not acc.access_token:
            return {"success": False,
                    "error": "No WABA account with credentials + phone_number_id."}

        Log = request.env["whatsapp.call.log"].sudo()
        # Temporary call_id; the real one from Meta overwrites it on connect.
        vals = {
            "call_id":              f"pending_{request.env.uid}_{to_number}",
            "call_direction":       "outgoing",
            "from_number":          acc.phone_number or acc.phone_number_id,
            "to_number":             to_number,
            "call_status":          "ringing",
            "meta_phone_number_id": acc.phone_number_id,
            "partner_id":           partner_id or False,
            # Stamp the dial time so outbound calls show up on the list
            # + kanban immediately — Meta's connect webhook may arrive
            # seconds later.
            "call_timestamp":       fields.Datetime.now(),
        }
        # chatbot_id is only present when the glue module
        # comm_whatsapp_calling_chatbot is installed. Set it defensively.
        if chatbot_id and "chatbot_id" in Log._fields:
            vals["chatbot_id"] = chatbot_id
        call_log = Log.create(vals)
        meta_call_id = call_log.action_connect(sdp_offer, to_number)
        if not meta_call_id:
            call_log.write({"call_status": "ended"})
            return {"success": False, "error": "Meta rejected the connect."}
        return {
            "success":       True,
            "call_log_id":   call_log.id,
            "meta_call_id":  meta_call_id if isinstance(meta_call_id, str) else call_log.call_id,
        }

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
        # Route by direction + status:
        #   inbound  + ringing  → reject   (turn down the incoming call)
        #   inbound  + answered → terminate (hang up an active call)
        #   outbound + anything → terminate (only valid outbound action)
        # Meta rejects reject on outbound calls (131055 method not
        # allowed) — that verb is reserved for turning down inbound.
        if call_log.call_direction == "outgoing":
            ok = call_log.action_hangup()
        elif call_log.call_status == "answered":
            ok = call_log.action_hangup()
        else:
            ok = call_log.action_decline()
        if ok:
            return {"success": True}
        return {"success": False, "error": "Decline failed"}

