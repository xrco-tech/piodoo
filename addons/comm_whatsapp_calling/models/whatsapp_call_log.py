# -*- coding: utf-8 -*-

import json
import logging
import re
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

    def _get_comm_whatsapp_config(self):
        """Read token and phone_number_id from comm_whatsapp config."""
        IrConfig = self.env["ir.config_parameter"].sudo()
        token = IrConfig.get_param("comm_whatsapp.access_token") or IrConfig.get_param(
            "comm_whatsapp.long_lived_token"
        )
        phone_number_id = IrConfig.get_param("comm_whatsapp.phone_number_id")
        return token, phone_number_id

    def _send_call_action_to_meta(self, action, sdp_answer=None):
        """POST pre_accept / accept / decline to Meta Graph API."""
        self.ensure_one()
        token, phone_number_id = self._get_comm_whatsapp_config()
        if not token or not phone_number_id:
            _logger.warning("comm_whatsapp_calling: missing access_token or phone_number_id")
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
        Meta requires SHA-256 fingerprint and valid format.
        For real audio you need browser WebRTC or a media server; this satisfies the API.
        """
        if not offer_sdp or not offer_sdp.strip():
            return None
        offer = offer_sdp.strip().replace("\r\n", "\n").split("\n")
        answer = []
        in_media = False
        for line in offer:
            if line.startswith("v="):
                answer.append(line)
            elif line.startswith("o="):
                answer.append("o=- %s 0 IN IP4 127.0.0.1" % int(time.time()))
            elif line.startswith("s="):
                answer.append("s=-")
            elif line.startswith("t="):
                answer.append("t=0 0")
            elif line.startswith("m="):
                in_media = True
                answer.append(line)
                answer.append("c=IN IP4 0.0.0.0")
            elif line.startswith("c=") and in_media:
                pass
            elif line.startswith("a=fingerprint:"):
                if "SHA-256" in line.upper() or "sha-256" in line.lower():
                    answer.append(re.sub(r"(?i)sha-384|sha-512", "", line))
            elif line.startswith("a=") and in_media:
                if line.startswith("a=rtpmap:") or line.startswith("a=fmtp:"):
                    answer.append(line)
                elif line == "a=sendrecv":
                    answer.append("a=sendrecv")
            elif not line.startswith("a=ice-") and line.strip():
                answer.append(line)
        return "\r\n".join(answer) if answer else None

    def action_pre_accept(self, sdp_answer=None):
        """Generate SDP if needed and send pre_accept to Meta."""
        self.ensure_one()
        if not sdp_answer and self.sdp_offer:
            sdp_answer = self._generate_simple_sdp_answer(self.sdp_offer)
            if sdp_answer:
                self.write({"sdp_answer": sdp_answer})
        return self._send_call_action_to_meta("pre_accept", sdp_answer=sdp_answer)

    def action_accept(self, sdp_answer=None):
        """Send accept to Meta (use stored or provided SDP answer)."""
        self.ensure_one()
        sdp = sdp_answer or self.sdp_answer
        if not sdp and self.sdp_offer:
            sdp = self._generate_simple_sdp_answer(self.sdp_offer)
            if sdp:
                self.write({"sdp_answer": sdp})
        res = self._send_call_action_to_meta("accept", sdp_answer=sdp)
        if res:
            self.write({"call_status": "answered"})
        return res

    def action_decline(self):
        """Send decline to Meta."""
        self.ensure_one()
        res = self._send_call_action_to_meta("decline")
        if res:
            self.write({"call_status": "declined"})
        return res
