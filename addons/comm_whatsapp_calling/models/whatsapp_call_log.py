# -*- coding: utf-8 -*-

import json
import logging
import time
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Meta Graph API version for calls
META_GRAPH_VERSION = "v21.0"


class WhatsappCallLog(models.Model):
    _name = "whatsapp.call.log"
    _description = "WhatsApp Call Log (comm_whatsapp_calling)"
    _order = "call_timestamp desc, id desc"

    call_id = fields.Char("Call ID", required=True, index=True, readonly=True)
    partner_id = fields.Many2one("res.partner", "Contact", ondelete="set null")
    from_number = fields.Char("From", required=True, readonly=True)
    to_number = fields.Char("To", required=True, readonly=True)
    call_direction = fields.Selection(
        [("incoming", "Incoming"), ("outgoing", "Outgoing")],
        required=True,
        default="incoming",
    )
    call_status = fields.Selection(
        [
            ("ringing", "Ringing"),
            ("calling", "Calling"),
            ("answered", "Answered"),
            ("ended", "Ended"),
            ("declined", "Declined"),
            ("failed", "Failed"),
        ],
        string="Status",
        default="ringing",
        index=True,
    )
    call_timestamp = fields.Datetime("Call Time", readonly=True)
    end_timestamp = fields.Datetime("End Time", readonly=True)
    duration = fields.Integer("Duration (seconds)", readonly=True)

    sdp_offer = fields.Text("SDP Offer", readonly=True)
    sdp_answer = fields.Text("SDP Answer", readonly=True)
    raw_data = fields.Text("Raw Webhook Data", readonly=True)
    meta_phone_number_id = fields.Char(
        "Meta Phone Number ID",
        readonly=True,
        help="Phone number ID from webhook metadata; used for API calls when set.",
    )

    def _get_comm_whatsapp_config(self):
        """
        Resolve (access_token, phone_number_id) for outbound Meta API calls.

        Priority (matches the same resolver used by whatsapp.flow and
        whatsapp.template so a fresh account-level token wins over the
        legacy system param that tends to go stale on long-running
        installs):
          1. The comm.whatsapp.account whose phone_number_id matches the
             call log's meta_phone_number_id. This is the number Meta
             routed the call to, so its credentials are correct by
             construction.
          2. The default active comm.whatsapp.account (single-WABA
             installs).
          3. Legacy ir.config_parameter fallback for older installs
             that never migrated to accounts.
        """
        Account = self.env["comm.whatsapp.account"].sudo()
        acc = self.env["comm.whatsapp.account"]
        if self and len(self) == 1 and self.meta_phone_number_id:
            acc = Account.find_for_phone_number_id(self.meta_phone_number_id)
        if not acc:
            acc = Account.get_default()

        if acc and acc.access_token:
            phone_number_id = (
                self.meta_phone_number_id
                if (self and len(self) == 1 and self.meta_phone_number_id)
                else acc.phone_number_id
            )
            return acc.access_token, phone_number_id

        # Legacy fallback.
        IrConfig = self.env["ir.config_parameter"].sudo()
        token = IrConfig.get_param("comm_whatsapp.access_token") \
            or IrConfig.get_param("comm_whatsapp.long_lived_token")
        phone_number_id = None
        if self and len(self) == 1 and self.meta_phone_number_id:
            phone_number_id = self.meta_phone_number_id
        if not phone_number_id:
            phone_number_id = IrConfig.get_param("comm_whatsapp.phone_number_id")
        return token, phone_number_id

    def _send_call_action_to_meta(self, action, sdp_answer=None):
        """POST pre_accept / accept / decline to Meta Graph API."""
        self.ensure_one()
        token, phone_number_id = self._get_comm_whatsapp_config()
        if not token or not phone_number_id:
            _logger.warning(
                "comm_whatsapp_calling: missing access_token or phone_number_id. "
                "Set them in Settings → WhatsApp (same as comm_whatsapp). "
                "phone_number_id can also be set from webhook metadata when an incoming call is received."
            )
            return False
        url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/calls"
        payload = {
            "messaging_product": "whatsapp",
            "call_id": self.call_id,
            "action": action,
        }
        if sdp_answer and action in ("pre_accept", "accept"):
            payload["session"] = {"sdp_type": "answer", "sdp": sdp_answer}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.ok:
                _logger.info("comm_whatsapp_calling: sent %s for call %s", action, self.call_id)
                return True
            _logger.error("comm_whatsapp_calling: %s failed: %s", action, r.text)
            return False
        except Exception as e:
            _logger.error("comm_whatsapp_calling: %s error: %s", action, e)
            return False

    def _generate_simple_sdp_answer(self, offer_sdp):
        """
        Generate a minimal SDP answer from the offer (server-side).
        Meta requires: SHA-256 fingerprint (capital letters), valid WebRTC structure.
        For real audio you need browser WebRTC or a media server; this satisfies the API.
        """
        if not offer_sdp or not offer_sdp.strip():
            return None
        try:
            offer_lines = offer_sdp.strip().replace("\r\n", "\n").split("\n")
            fingerprint_hash = None
            ice_ufrag = None
            ice_pwd = None
            audio_port = "9"
            audio_protocol = "RTP/AVP"
            audio_formats = []
            rtpmap_lines = []

            for line in offer_lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("a=fingerprint:"):
                    # Meta requires "SHA-256" in capital letters; extract hash only
                    rest = line.split(":", 1)[-1].strip()
                    if "sha-256" in rest.lower():
                        parts = rest.split(None, 1)
                        if len(parts) >= 2:
                            fingerprint_hash = parts[1]
                        else:
                            fingerprint_hash = rest
                    elif "SHA-256" in rest:
                        parts = rest.split(None, 1)
                        if len(parts) >= 2:
                            fingerprint_hash = parts[1]
                        else:
                            fingerprint_hash = rest
                elif line.startswith("a=ice-ufrag:"):
                    ice_ufrag = line.split(":", 1)[1].strip()
                elif line.startswith("a=ice-pwd:"):
                    ice_pwd = line.split(":", 1)[1].strip()
                elif line.startswith("m=audio"):
                    parts = line.split()
                    if len(parts) >= 4:
                        audio_port = parts[1]
                        audio_protocol = parts[2]
                        audio_formats = parts[3:]
                elif line.startswith("a=rtpmap:"):
                    rtpmap_lines.append(line)

            if not fingerprint_hash:
                _logger.warning("comm_whatsapp_calling: no SHA-256 fingerprint in offer, SDP may be rejected")
                return None

            answer_lines = [
                "v=0",
                "o=- %s 0 IN IP4 127.0.0.1" % int(time.time()),
                "s=-",
                "t=0 0",
                "a=group:BUNDLE audio",
                "a=msid-semantic: WMS",
            ]
            preferred = audio_formats[0] if audio_formats else "0"
            answer_lines.append("m=audio %s %s %s" % (audio_port, audio_protocol, preferred))
            answer_lines.append("c=IN IP4 0.0.0.0")
            answer_lines.append("a=ice-ufrag:%s" % (ice_ufrag or "answer"))
            answer_lines.append("a=ice-pwd:%s" % (ice_pwd or "answer-password"))
            # Meta requires capital "SHA-256" in fingerprint
            answer_lines.append("a=fingerprint:SHA-256 %s" % fingerprint_hash.strip())
            answer_lines.append("a=setup:active")
            answer_lines.append("a=mid:audio")
            answer_lines.append("a=sendrecv")
            for r in rtpmap_lines:
                answer_lines.append(r)

            return "\r\n".join(answer_lines)
        except Exception as e:
            _logger.exception("comm_whatsapp_calling: _generate_simple_sdp_answer failed: %s", e)
            return None

    def action_pre_accept(self, sdp_answer=None):
        """Send pre_accept to Meta. This tells Meta 'we are preparing to
        accept'; no SDP answer required at this stage — the browser only
        provides an SDP when it's ready to accept."""
        self.ensure_one()
        return self._send_call_action_to_meta("pre_accept")

    def action_accept(self, sdp_answer=None):
        """Send accept to Meta with the browser-generated SDP answer.

        Refuses when no answer is provided — the old server-side fake
        SDP generator produced a syntactically-valid but cryptographically
        invalid answer that Meta accepted at the protocol layer but that
        never established a DTLS-SRTP session, so no audio ever flowed.
        Real audio requires a browser RTCPeerConnection to build the SDP.
        """
        self.ensure_one()
        sdp = sdp_answer or self.sdp_answer
        if not sdp:
            _logger.warning(
                "comm_whatsapp_calling: refusing to accept call %s — "
                "no SDP answer from the browser. The popup should call "
                "/whatsapp/call/answer with sdp_answer=<real SDP>.",
                self.call_id,
            )
            return False
        # Persist the browser's SDP so the log stays complete.
        if sdp != self.sdp_answer:
            self.write({"sdp_answer": sdp})
        res = self._send_call_action_to_meta("accept", sdp_answer=sdp)
        if res:
            self.write({"call_status": "answered"})
        return res

    def action_decline(self):
        """Send reject to Meta. The Meta API's allowed action enum is
        [accept, connect, media_update, pre_accept, reject, terminate];
        `decline` returns a schema error. `reject` is the correct verb
        for a ringing call the user chooses not to pick up."""
        self.ensure_one()
        res = self._send_call_action_to_meta("reject")
        if res:
            self.write({"call_status": "declined"})
        return res

    def action_connect(self, sdp_offer, to_number):
        """Initiate an outbound WhatsApp call. The browser has already
        created an RTCPeerConnection, captured the user's mic, and built
        an SDP offer. We POST that offer to Meta's /{PNID}/calls with
        action=connect. Meta places the call to `to_number`; when the
        recipient picks up, Meta fires a webhook with the answer SDP.

        Returns the Meta call_id when Meta accepted the offer, else None.
        """
        self.ensure_one()
        if not sdp_offer:
            _logger.warning(
                "comm_whatsapp_calling: connect refused — missing sdp_offer"
            )
            return None
        if not to_number:
            _logger.warning(
                "comm_whatsapp_calling: connect refused — missing to_number"
            )
            return None
        token, phone_number_id = self._get_comm_whatsapp_config()
        if not token or not phone_number_id:
            _logger.warning(
                "comm_whatsapp_calling: connect refused — missing "
                "access_token or phone_number_id."
            )
            return None
        url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/calls"
        payload = {
            "messaging_product": "whatsapp",
            "to":     to_number,
            "action": "connect",
            "session": {"sdp_type": "offer", "sdp": sdp_offer},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.ok:
                data = r.json() or {}
                # Meta returns { messaging_product, calls: [{id: "wacid.…"}] }.
                meta_call_id = None
                calls = data.get("calls") or []
                if calls:
                    meta_call_id = calls[0].get("id")
                _logger.info(
                    "comm_whatsapp_calling: connect dispatched, meta_call_id=%s",
                    meta_call_id,
                )
                update = {"sdp_offer": sdp_offer, "call_status": "ringing"}
                if meta_call_id and not self.call_id.startswith("wacid."):
                    update["call_id"] = meta_call_id
                self.write(update)
                return meta_call_id or True
            _logger.error(
                "comm_whatsapp_calling: connect failed (%s): %s",
                r.status_code, r.text[:400],
            )
            return None
        except Exception as e:
            _logger.error("comm_whatsapp_calling: connect error: %s", e)
            return None

    def action_hangup(self):
        """End an already-answered call. Meta uses `terminate` for this
        (not `reject`, which is only valid while ringing)."""
        self.ensure_one()
        res = self._send_call_action_to_meta("terminate")
        if res:
            self.write({"call_status": "ended"})
        return res
