# -*- coding: utf-8 -*-
"""WebRTC signalling relay + ICE credentials for WhatsApp call monitoring.

The agent and supervisor browsers never talk directly — they exchange SDP/ICE
through /whatsapp/monitor/signal, which pushes each message onto the target
user's bus channel. /whatsapp/monitor/ice_servers hands out STUN/TURN servers
with short-lived coturn REST credentials.
"""
import base64
import hashlib
import hmac
import logging
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsappMonitorController(http.Controller):

    @http.route('/whatsapp/monitor/signal', type='json', auth='user', methods=['POST'])
    def signal(self, monitor_id=None, to_partner_id=None, kind=None, data=None, **kw):
        """Relay one SDP/ICE message to the target user's bus channel."""
        monitor = request.env['comm.whatsapp.monitor'].sudo().browse(int(monitor_id or 0))
        if not monitor.exists():
            return {'ok': False, 'error': 'unknown monitor'}
        # Only the two parties of this monitor may signal on it: the supervisor,
        # or the agent who owns the call.
        uid = request.env.user.id
        if uid not in (monitor.supervisor_id.id, monitor.agent_user_id.id,
                       monitor.call_log_id.create_uid.id):
            return {'ok': False, 'error': 'not a participant'}
        target = request.env['res.partner'].sudo().browse(int(to_partner_id or 0))
        if not target.exists():
            return {'ok': False, 'error': 'unknown target'}
        request.env['bus.bus'].sudo()._sendone(target, 'wa_monitor_signal', {
            'monitor_id': monitor.id, 'kind': kind, 'data': data,
        })
        return {'ok': True}

    @http.route('/whatsapp/monitor/ice_servers', type='json', auth='user', methods=['POST'])
    def ice_servers(self, **kw):
        """STUN/TURN for the relay. coturn runs with --use-auth-secret, so we
        mint short-lived REST credentials (username = <expiry>:<uid>, password =
        base64(HMAC-SHA1(secret, username))). Falls back to public STUN when no
        TURN is configured (fine for same-network P2P; TURN needed across NAT)."""
        ICP = request.env['ir.config_parameter'].sudo()
        servers = []
        turn_url = ICP.get_param('comm_whatsapp_calling.turn_url')       # e.g. turn:host:3478
        turn_secret = ICP.get_param('comm_whatsapp_calling.turn_secret')
        stun_url = ICP.get_param('comm_whatsapp_calling.stun_url') or 'stun:stun.l.google.com:19302'
        servers.append({'urls': [stun_url]})
        if turn_url and turn_secret:
            ttl = int(ICP.get_param('comm_whatsapp_calling.turn_ttl') or 3600)
            username = '%d:%d' % (int(time.time()) + ttl, request.env.user.id)
            digest = hmac.new(turn_secret.encode(), username.encode(), hashlib.sha1).digest()
            credential = base64.b64encode(digest).decode()
            urls = [u.strip() for u in turn_url.split(',') if u.strip()]
            servers.append({'urls': urls, 'username': username, 'credential': credential})
        return {'iceServers': servers}
