# -*- coding: utf-8 -*-
import logging
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CommDialerCampaign(models.Model):
    _name = 'comm.dialer.campaign'
    _description = 'Outbound Dialer Campaign'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    mode = fields.Selection([
        ('preview', 'Preview'),
        ('progressive', 'Progressive'),
        ('predictive', 'Predictive'),
    ], default='progressive', required=True,
        help="Preview: the agent triggers each call. "
             "Progressive: one call per free agent. "
             "Predictive: over-dial by a pacing ratio to minimise agent idle time.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('paused', 'Paused'),
        ('done', 'Done'),
    ], default='draft', required=True)

    account_id = fields.Many2one(
        'comm.voip.account', 'VoIP Account', required=True,
        domain="[('usage', 'in', ('automation', 'both'))]",
        help="Provider account used to originate calls (supplies the caller ID).")

    # Calling window (company timezone), 24h floats. Outside it the pacer sleeps.
    window_start = fields.Float('Call From', default=8.0,
                                help="Earliest hour to dial (24h, company tz).")
    window_end = fields.Float('Call Until', default=17.0,
                              help="Latest hour to dial (24h, company tz).")

    # Retry policy.
    max_attempts = fields.Integer('Max Attempts', default=3)
    retry_gap_hours = fields.Float('Retry Gap (h)', default=4.0,
                                   help="Minimum hours between attempts on the same contact.")

    # Pacing (predictive).
    pacing_ratio = fields.Float('Pacing Ratio', default=1.0,
                                help="Lines to open per ready agent. 1.0 = progressive; "
                                     ">1.0 over-dials (predictive).")
    target_abandon_rate = fields.Float('Target Abandon %', default=3.0,
                                       help="Predictive governor cap: the pacer holds back to "
                                            "keep dropped (abandoned) calls at or below this.")
    max_lines = fields.Integer('Max Concurrent Lines', default=0,
                               help="Hard cap on simultaneous live calls (0 = unlimited).")

    contact_ids = fields.One2many('comm.dialer.contact', 'campaign_id', 'Contacts')
    session_ids = fields.One2many('comm.dialer.agent.session', 'campaign_id', 'Agents')

    # Stats.
    contact_total = fields.Integer(compute='_compute_stats')
    contact_pending = fields.Integer(compute='_compute_stats')
    contact_done = fields.Integer(compute='_compute_stats')
    ready_agents = fields.Integer('Ready Agents', compute='_compute_stats')
    live_calls = fields.Integer('Live Calls', compute='_compute_stats')
    connect_rate = fields.Float('Connect %', compute='_compute_stats')
    abandon_rate = fields.Float('Abandon %', compute='_compute_stats')

    def _compute_stats(self):
        Call = self.env['comm.voip.call']
        for c in self:
            contacts = c.contact_ids
            c.contact_total = len(contacts)
            c.contact_pending = len(contacts.filtered(lambda r: r.state in ('pending', 'retry')))
            c.contact_done = len(contacts.filtered(
                lambda r: r.state in ('contacted', 'dnc', 'failed', 'done')))
            c.ready_agents = len(c.session_ids.filtered(lambda s: s.state == 'ready'))
            base = [('dialer_contact_id.campaign_id', '=', c.id)]
            c.live_calls = Call.search_count(
                base + [('state', 'in', ('queued', 'ringing', 'in_progress'))])
            attempted = Call.search_count(base)
            connected = Call.search_count(
                base + [('state', 'in', ('in_progress', 'completed'))])
            abandoned = Call.search_count(base + [('state', '=', 'cancelled')])
            c.connect_rate = (100.0 * connected / attempted) if attempted else 0.0
            c.abandon_rate = (100.0 * abandoned / connected) if connected else 0.0

    # ── State transitions ────────────────────────────────────────────────
    def action_start(self):
        for c in self:
            if not c.contact_ids:
                raise UserError(_("Add contacts before starting the campaign."))
            c.state = 'running'

    def action_pause(self):
        self.write({'state': 'paused'})

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_mark_done(self):
        self.write({'state': 'done'})

    # ── Pacing ───────────────────────────────────────────────────────────
    def _within_window(self):
        self.ensure_one()
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        hour = now.hour + now.minute / 60.0
        if self.window_start <= self.window_end:
            return self.window_start <= hour < self.window_end
        # Window crosses midnight.
        return hour >= self.window_start or hour < self.window_end

    def _next_contact(self):
        """Next eligible call-list row: pending/retry, under the attempt cap,
        and whose retry time (if any) has arrived."""
        self.ensure_one()
        now = fields.Datetime.now()
        return self.env['comm.dialer.contact'].search([
            ('campaign_id', '=', self.id),
            ('state', 'in', ('pending', 'retry')),
            ('attempts', '<', self.max_attempts),
            '|', ('next_attempt', '=', False), ('next_attempt', '<=', now),
        ], order='sequence, id', limit=1)

    def _lines_to_open(self, ready_count, room):
        """How many new call legs to open this tick."""
        self.ensure_one()
        if self.mode == 'preview':
            return 0
        if self.mode == 'progressive':
            base = ready_count
        else:  # predictive — over-dial by the pacing ratio, governed elsewhere.
            base = math.ceil(ready_count * max(self.pacing_ratio, 1.0))
        return max(0, min(base, room))

    def _pace_once(self):
        self.ensure_one()
        if self.state != 'running' or not self._within_window():
            return
        ready = self.session_ids.filtered(lambda s: s.state == 'ready')
        if not ready:
            if not self._next_contact():
                self.state = 'done'
            return

        room = (self.max_lines - self.live_calls) if self.max_lines else 9999
        if room <= 0:
            return

        lines = self._lines_to_open(len(ready), room)
        free_agents = list(ready)
        opened = 0
        for i in range(lines):
            contact = self._next_contact()
            if not contact:
                break
            # In progressive mode we hand the call to a specific ready agent; in
            # predictive mode we over-dial and bind an agent on answer (webhook).
            agent = free_agents[i] if (self.mode == 'progressive' and i < len(free_agents)) \
                else self.env['comm.dialer.agent.session']
            contact._originate(self, agent)
            opened += 1

        if opened == 0 and not self._next_contact():
            self.state = 'done'

    @api.model
    def _cron_pace(self):
        """Cron entry point — paces every running campaign. Disabled by default;
        enable the cron once a real provider is wired into originate()/bridge()."""
        for c in self.search([('state', '=', 'running')]):
            try:
                c._pace_once()
            except Exception:  # one bad campaign must not stall the rest
                _logger.exception("Dialer pacing failed for campaign %s", c.id)
