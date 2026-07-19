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

    @http.route("/whatsapp/call/presence/get", type="json", auth="user")
    def get_presence(self, **kwargs):
        """Return the current user's call presence. Uses sudo so a
        regular user can read their own value regardless of ACL."""
        user = request.env.user.sudo()
        return {"presence": user.wa_call_presence or "available"}

    @http.route("/whatsapp/call/presence/set", type="json", auth="user",
                methods=["POST"])
    def set_presence(self, presence=None, **kwargs):
        """Update the current user's call presence. Regular users can't
        write to res.users directly, so we sudo — but we only ever write
        the current user's own record, not somebody else's."""
        allowed = {"available", "away", "dnd"}
        if presence not in allowed:
            return {"success": False, "error": "invalid presence"}
        request.env.user.sudo().write({"wa_call_presence": presence})
        return {"success": True, "presence": presence}

    @http.route(
        "/whatsapp/call/transfer/<int:call_log_id>",
        type="json", auth="user", methods=["POST"],
    )
    def transfer_call(self, call_log_id, team_id=None, **kwargs):
        """Initiate a mid-call transfer. Meta's Business Calling API
        doesn't natively support conference / warm transfer, so this is
        a cold transfer:

          1. Mark the source call as transferred.
          2. Broadcast a whatsapp_transfer_request to every Available
             member of the target team.
          3. Return success; the source agent's UI tears down its own
             leg.
          4. The first team member to accept the request kicks off an
             outbound call back to the customer via the standard dial
             path, tagged with transferred_from_call_log_id.

        Client-side: the receiving popup calls svc.dialCall() after
        accept; server-side glue in this route only fires the bus event.
        """
        call_log = request.env["whatsapp.call.log"].sudo().browse(call_log_id)
        if not call_log.exists():
            return {"success": False, "error": "Call not found"}
        if call_log.call_status != "answered":
            return {"success": False,
                    "error": "Only answered calls can be transferred."}
        team = request.env["whatsapp.call.team"].sudo().browse(int(team_id or 0))
        if not team.exists() or not team.active:
            return {"success": False, "error": "Team not found"}

        # Restrict the target set to Available team members so the
        # source agent doesn't hand off to an Away team.
        targets = team.member_ids.filtered(
            lambda u: u.active and u.wa_call_presence == "available"
        )
        # Exclude the transferring agent so they don't ring themselves.
        targets = targets - request.env.user

        if not targets:
            return {"success": False,
                    "error": f"No Available agent in {team.name}."}

        call_log.write({
            "transferred_from_user_id": request.env.uid,
            "transferred_to_team_id":   team.id,
        })

        payload = {
            "type":                   "whatsapp_transfer_request",
            "source_call_log_id":     call_log.id,
            "from_number":            call_log.from_number or "",
            "to_number":              call_log.to_number or "",
            "partner_id":             call_log.partner_id.id if call_log.partner_id else False,
            "partner_name":           call_log.partner_id.name if call_log.partner_id
                                       else (call_log.from_number or "Caller"),
            "transferred_from_uid":   request.env.uid,
            "transferred_from_name":  request.env.user.name,
            "team_id":                team.id,
            "team_name":              team.name,
            # The receiving side needs to know which WABA to dial from.
            "account_id":             call_log.account_id.id if call_log.account_id else None,
        }
        bus = request.env["bus.bus"].sudo()
        n = 0
        for u in targets:
            if u.partner_id:
                try:
                    bus._sendone(
                        u.partner_id,
                        "whatsapp_transfer_request",
                        payload,
                    )
                    n += 1
                except AttributeError:
                    break
        _logger.info(
            "comm_whatsapp_calling: transfer requested by %s → team %s "
            "(call %s, %s targets)",
            request.env.user.name, team.name, call_log.id, n,
        )
        return {"success": True, "targets_notified": n}

    @http.route("/whatsapp/call/teams", type="json", auth="user")
    def list_teams(self, **kwargs):
        """Return active call teams for the transfer picker. Each team's
        available-member count is included so the source agent can see
        at a glance whether the target has anyone to ring."""
        Team = request.env["whatsapp.call.team"].sudo()
        teams = Team.search([("active", "=", True)], order="sequence, name")
        out = []
        for t in teams:
            available = t.member_ids.filtered(
                lambda u: u.active and u.wa_call_presence == "available"
            )
            out.append({
                "id":               t.id,
                "name":             t.name,
                "available_count":  len(available),
                "member_count":     len(t.member_ids),
            })
        return {"teams": out}

    @http.route("/whatsapp/call/accounts", type="json", auth="user")
    def list_accounts(self, **kwargs):
        """Return the active WABA accounts the current user could dial
        from, with the default flagged. Used by the systray dialer to
        show a picker when there's more than one."""
        Account = request.env["comm.whatsapp.account"].sudo()
        accounts = Account.search([
            ("active", "=", True),
            ("access_token", "!=", False),
            ("phone_number_id", "!=", False),
        ], order="sequence, id")
        default = Account.get_default()
        return {
            "accounts": [{
                "id":            a.id,
                "name":          a.name,
                "phone_number":  a.phone_number,
                "phone_number_id": a.phone_number_id,
                "is_default":    a.id == (default.id if default else False),
                "token_status":  a.token_status,
            } for a in accounts],
            "default_id": default.id if default else None,
        }

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
            # Direct-set the account so the compute doesn't overwrite it
            # if the phone_number_id fingerprint changes.
            "account_id":           acc.id,
        }
        # chatbot_id is only present when the glue module
        # comm_whatsapp_calling_chatbot is installed. Set it defensively.
        if chatbot_id and "chatbot_id" in Log._fields:
            vals["chatbot_id"] = chatbot_id
        call_log = Log.create(vals)
        connect_result = call_log.action_connect(sdp_offer, to_number)
        if not connect_result.get("success"):
            call_log.write({"call_status": "ended"})
            return {"success": False,
                    "error": connect_result.get("error") or "Meta rejected the connect."}
        meta_call_id = connect_result.get("meta_call_id")
        return {
            "success":       True,
            "call_log_id":   call_log.id,
            "meta_call_id":  meta_call_id if isinstance(meta_call_id, str) else call_log.call_id,
        }

    @http.route(
        "/whatsapp/call/request_permission",
        type="json", auth="user", methods=["POST"],
    )
    def request_call_permission(self, to_number=None, account_id=None, **kwargs):
        """Send the business's call-permission-request WhatsApp template
        to a recipient — offered to the agent right after a dial fails
        with Meta's "No approved call permission from the recipient"
        error. Looks for a whatsapp.template literally named
        "call_permission_request" (case-insensitive) that Meta has
        approved; {"success": False, "error": "template_missing"} when
        none exists, so the UI can show an actionable message instead
        of silently failing."""
        if not to_number:
            return {"success": False, "error": "Missing recipient number."}

        Template = request.env["whatsapp.template"].sudo()
        domain = [("name", "=ilike", "call_permission_request"),
                  ("status", "=", "APPROVED")]
        template = Template.browse()
        if account_id:
            template = Template.search(
                domain + [("account_id", "=", int(account_id))], limit=1)
        if not template:
            template = Template.search(domain, limit=1)
        if not template:
            return {"success": False, "error": "template_missing"}

        return template._send_simple(to_number)

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

