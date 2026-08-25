# -*- coding: utf-8 -*-
"""Supervisor call monitoring — Listen / Whisper / Barge.

A supervisor picks a live call and a mode; this creates a request row that the
dialer_ari service polls (like queued calls). The service originates the
supervisor's softphone into Asterisk's ChanSpy on the agent's channel:

    Listen  -> ChanSpy(PJSIP/<agent>, q)    hear both, talk to neither
    Whisper -> ChanSpy(PJSIP/<agent>, qw)   talk to the AGENT only
    Barge   -> ChanSpy(PJSIP/<agent>, qB)   talk to both (3-way)

Every session is a persisted record, so who monitored which call is auditable
(POPIA: monitoring is covert to the customer and needs a lawful basis + the
standard "calls may be monitored" disclosure).
"""
from odoo import fields, models

# mode -> ChanSpy options (consumed by the dialer_ari service / dialplan).
SPY_OPTS = {'listen': 'q', 'whisper': 'qw', 'barge': 'qB'}


class CommDialerBarge(models.Model):
    _name = 'comm.dialer.barge'
    _description = 'Supervisor Call Monitor (Listen / Whisper / Barge)'
    _order = 'create_date desc'
    _rec_name = 'call_id'

    call_id = fields.Many2one(
        'comm.voip.call', 'Call', required=True, ondelete='cascade', index=True)
    supervisor_id = fields.Many2one(
        'res.users', 'Supervisor', required=True, index=True,
        default=lambda self: self.env.user)
    # Captured at request time: the SIP endpoints the service originates/spies.
    supervisor_ext = fields.Char('Supervisor SIP')
    agent_ext = fields.Char('Agent SIP')
    mode = fields.Selection(
        [('listen', 'Listen'), ('whisper', 'Whisper'), ('barge', 'Barge')],
        required=True, default='listen')
    state = fields.Selection([
        ('requested', 'Requested'),
        ('active', 'Active'),
        ('ended', 'Ended'),
        ('failed', 'Failed'),
    ], default='requested', index=True)
    # Set by the supervisor's Stop button; the service hangs up the spy channel.
    stop_requested = fields.Boolean('Stop Requested')
    external_channel_id = fields.Char('Spy Channel')
    error = fields.Char('Error')

    def spy_opts(self):
        self.ensure_one()
        return SPY_OPTS.get(self.mode, 'q')

    def action_stop(self):
        for b in self:
            if b.state == 'active':
                # Live: let the ARI service hang up the spy channel on its poll.
                b.stop_requested = True
            elif b.state == 'requested':
                # Never started — just close it out.
                b.state = 'ended'
        return True
