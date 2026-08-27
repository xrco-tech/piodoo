# -*- coding: utf-8 -*-
"""WhatsApp call monitoring — Phase 1: Listen (silent).

WhatsApp calls are browser<->Meta WebRTC (end-to-end encrypted), so there is no
server-side channel to spy on. A supervisor instead listens via a SECOND WebRTC
connection to the agent's browser, which relays a mix of both call legs. This
model is the request/audit/permission record; the media path is set up in the
browser (call_monitor.js) using bus signalling + coturn.

Signalling channels (bus):
  - broadcast 'wa_monitor_supervise'  -> 'wa_monitor_request' (agents; the one
    that owns the call answers with an SDP offer)
  - the supervisor's own partner      -> 'wa_monitor_start' / 'wa_monitor_signal'
  - 'wa_monitor_stop' to both to tear down.

POPIA: listening is covert to the customer — gated to supervisors and every
session is a persisted record; pair with the standard monitoring disclosure.
"""
from odoo import api, fields, models


class CommWhatsappMonitor(models.Model):
    _name = 'comm.whatsapp.monitor'
    _description = 'WhatsApp Call Monitor (Listen)'
    _order = 'create_date desc'
    _rec_name = 'call_log_id'

    call_log_id = fields.Many2one(
        'whatsapp.call.log', 'Call', required=True, ondelete='cascade', index=True)
    supervisor_id = fields.Many2one(
        'res.users', 'Supervisor', required=True, index=True,
        default=lambda self: self.env.user)
    agent_user_id = fields.Many2one('res.users', 'Agent')  # call owner, for audit
    mode = fields.Selection([
        ('listen', 'Listen'),    # hear both sides, talk to none
        ('whisper', 'Whisper'),  # talk to the agent only (customer can't hear)
        ('barge', 'Barge'),      # talk to both (agent + customer)
    ], default='listen', required=True)
    state = fields.Selection([
        ('requested', 'Requested'),
        ('active', 'Active'),
        ('ended', 'Ended'),
        ('failed', 'Failed'),
    ], default='requested', index=True)
    error = fields.Char('Error')

    def _payload(self):
        self.ensure_one()
        return {
            'monitor_id': self.id,
            'call_log_id': self.call_log_id.id,
            'supervisor_partner_id': self.supervisor_id.partner_id.id,
            'mode': self.mode,
        }

    def _notify_start(self):
        Bus = self.env['bus.bus']
        for m in self:
            payload = m._payload()
            # Broadcast to agents — the browser that owns this call answers.
            Bus._sendone('wa_monitor_supervise', 'wa_monitor_request', payload)
            # The supervisor's own browser prepares to receive the offer.
            Bus._sendone(m.supervisor_id.partner_id, 'wa_monitor_start', payload)

    @api.model
    def start(self, call_log_id, mode='listen'):
        call = self.env['whatsapp.call.log'].browse(call_log_id)
        if not call.exists():
            return False
        monitor = self.create({
            'call_log_id': call.id,
            'agent_user_id': call.create_uid.id,
            'mode': mode if mode in ('listen', 'whisper', 'barge') else 'listen',
        })
        monitor._notify_start()
        return monitor.id

    @api.model
    def start_listen(self, call_log_id):
        return self.start(call_log_id, 'listen')

    def action_stop(self):
        Bus = self.env['bus.bus']
        for m in self:
            if m.state in ('requested', 'active'):
                m.state = 'ended'
            payload = {'monitor_id': m.id}
            Bus._sendone('wa_monitor_supervise', 'wa_monitor_stop', payload)
            Bus._sendone(m.supervisor_id.partner_id, 'wa_monitor_stop', payload)
        return True

    @api.model
    def mark_active(self, monitor_id):
        m = self.browse(monitor_id)
        if m.exists() and m.state == 'requested':
            m.state = 'active'
        return True
