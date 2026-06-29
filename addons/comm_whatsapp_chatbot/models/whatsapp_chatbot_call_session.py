# -*- coding: utf-8 -*-
"""Live voice-call session record.

Created when an agent launches the Agent Workspace against a chatbot. Tracks
who the agent is, who they're talking to, which script they're running, and
the cumulative engine state. The OWL workspace ticks the session forward on
each agent action and reads its `session_state` to know where the engine is.
"""

from odoo import api, fields, models


class CommVoiceCallSession(models.Model):
    _name = 'comm.voice.call.session'
    _description = 'Voice Call Session'
    _order = 'started_at desc, id desc'

    name = fields.Char(string="Reference", compute='_compute_name', store=True)

    chatbot_id = fields.Many2one(
        'whatsapp.chatbot', string="Script", required=True,
        ondelete='restrict',
        domain=[('channel', '=', 'voice')],
    )
    agent_id = fields.Many2one(
        'res.users', string="Agent", required=True,
        default=lambda self: self.env.user,
        ondelete='restrict',
    )
    contact_id = fields.Many2one(
        'whatsapp.chatbot.contact', string="Customer Contact",
        ondelete='restrict',
        help="Customer the agent is speaking with. Backed by a res.partner.",
    )
    partner_id = fields.Many2one(
        'res.partner', related='contact_id.partner_id', string="Customer Partner",
        store=True,
    )

    started_at = fields.Datetime(string="Started", default=fields.Datetime.now,
                                 required=True, readonly=True)
    ended_at = fields.Datetime(string="Ended", readonly=True)
    duration_seconds = fields.Integer(
        string="Duration (s)", compute='_compute_duration', store=False,
    )

    # Session state mirrors the simulator's shape: where the engine is parked
    # so a turn can resume from there. Variables and call_stack live on the
    # contact (real records); only the cursor lives here.
    session_state = fields.Json(string="Session State", default=dict)

    outcome = fields.Selection([
        ('open',       'Open'),
        ('resolved',   'Resolved'),
        ('escalated',  'Escalated'),
        ('abandoned',  'Abandoned'),
        ('error',      'Error'),
    ], string="Outcome", default='open', tracking=True)
    notes = fields.Text(string="Wrap-up Notes")

    @api.depends('chatbot_id', 'partner_id', 'started_at')
    def _compute_name(self):
        for rec in self:
            who = rec.partner_id.name or '?'
            when = rec.started_at and rec.started_at.strftime('%Y-%m-%d %H:%M') or ''
            rec.name = f"{who} — {rec.chatbot_id.name or 'Script'} ({when})"

    @api.depends('started_at', 'ended_at')
    def _compute_duration(self):
        for rec in self:
            if rec.started_at and rec.ended_at:
                rec.duration_seconds = int(
                    (rec.ended_at - rec.started_at).total_seconds()
                )
            else:
                rec.duration_seconds = 0

    def action_close(self, outcome='resolved', notes=None):
        """Close out a call session. Called by the workspace's wrap-up action."""
        self.ensure_one()
        vals = {'outcome': outcome, 'ended_at': fields.Datetime.now()}
        if notes is not None:
            vals['notes'] = notes
        self.write(vals)
        return True
