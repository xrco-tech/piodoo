# -*- coding: utf-8 -*-
import logging
import math
import random

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

    # ── Dry-run (simulated telephony — no provider needed) ────────────────
    simulate = fields.Boolean(
        'Dry-run (simulate)',
        help="Run the whole loop against a SIMULATED telephony backend — no Vox / "
             "Asterisk needed. Calls advance one stage per tick (queued → ringing → "
             "answered/bridged → completed) so you can watch progressive and "
             "predictive work in the UI.")
    sim_answer_rate = fields.Float('Sim Answer Rate', default=0.35,
                                   help="Fraction of dialled calls a human/machine picks up.")
    sim_machine_rate = fields.Float('Sim Machine Rate', default=0.1,
                                    help="Fraction of answered calls that are answering machines (AMD).")

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

    def _answer_rate(self, window=200):
        """Rolling answer rate (answered / dialed) over the last `window`
        attempts on this campaign. Falls back to a cold-start assumption until
        enough calls have accumulated to be meaningful."""
        self.ensure_one()
        Call = self.env['comm.voip.call']
        dialed = Call.search([('dialer_contact_id.campaign_id', '=', self.id)],
                             order='id desc', limit=window)
        if len(dialed) < 20:
            return 0.35  # cold-start guess until real data lands
        answered = len(dialed.filtered(lambda c: c.state in ('in_progress', 'completed')))
        return max(0.05, answered / len(dialed))

    def _lines_to_open(self, ready_count, room, live=0):
        """How many new call legs to open this tick.

        Progressive: one line per free agent.
        Predictive: over-dial by pacing_ratio ÷ live answer-rate, then apply an
        abandon governor so expected dropped calls stay within target_abandon_rate,
        and subtract calls already in flight so we target a concurrency level
        rather than stacking every tick."""
        self.ensure_one()
        if self.mode == 'preview' or ready_count <= 0:
            return 0
        if self.mode == 'progressive':
            return max(0, min(ready_count, room))

        # Predictive.
        ar = self._answer_rate()
        t = min(0.99, max(0.0, self.target_abandon_rate / 100.0))
        # Governor: cap concurrent answers so abandon rate (1 - agents/answers) <= t
        #   answers <= ready / (1 - t)   =>   lines <= answers / ar
        lines_cap = math.floor((ready_count / max(1e-3, 1 - t)) / ar)
        desired = math.ceil(ready_count / ar * max(self.pacing_ratio, 1.0))
        target_total = min(desired, lines_cap)
        return max(0, min(target_total - live, room))

    def _pace_once(self):
        self.ensure_one()
        if self.state != 'running' or not self._within_window():
            return
        ready = self.session_ids.filtered(lambda s: s.state == 'ready')
        if not ready:
            if not self._next_contact():
                self.state = 'done'
            return

        # Count in-flight directly — the live_calls computed field is not stored
        # and can be stale within a transaction, which would break pacing.
        live = self.env['comm.voip.call'].search_count([
            ('dialer_campaign_id', '=', self.id),
            ('state', 'in', ('queued', 'ringing', 'in_progress')),
        ])
        if self.max_lines:
            room = self.max_lines - live
        else:
            # Soft safety cap when unlimited, so a bug can't dial the world.
            room = max(0, math.ceil(len(ready) * 5) - live)
        if room <= 0:
            return

        lines = self._lines_to_open(len(ready), room, live)
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
        for c in self.search([('state', '=', 'running'), ('simulate', '=', False)]):
            try:
                c._pace_once()
            except Exception:  # one bad campaign must not stall the rest
                _logger.exception("Dialer pacing failed for campaign %s", c.id)

    # ── Dry-run simulation ───────────────────────────────────────────────
    # Stands in for the ARI bridge service: advances each call one stage per
    # tick and drives the exact same agent-state + retry transitions real
    # telephony would, using simulated answer/AMD outcomes.
    def action_sim_tick(self):
        for c in self:
            c._simulate_tick()
        return True

    def action_reset_contacts(self):
        """Re-arm the call list and clear simulated calls, for repeat dry-runs."""
        for c in self:
            c.contact_ids.write({'state': 'pending', 'attempts': 0,
                                 'next_attempt': False, 'last_disposition_id': False})
            c.mapped('contact_ids.call_ids').unlink()
            c.session_ids.filtered(lambda s: s.state != 'offline').write(
                {'state': 'ready', 'current_call_id': False})
        return True

    def _sim_release(self, session, to_state):
        if session:
            session.write({'state': to_state, 'current_call_id': False,
                           'last_state_change': fields.Datetime.now()})

    def _simulate_tick(self):
        self.ensure_one()
        if not self.simulate or self.state != 'running':
            return
        Call = self.env['comm.voip.call']
        now = fields.Datetime.now()
        base = [('dialer_campaign_id', '=', self.id)]

        # 0. Wrap-up completes → agents return to Ready (keeps the loop flowing).
        self.session_ids.filtered(lambda s: s.state == 'wrap')._set_state('ready')

        # 1. In-progress calls finish → completed.
        for call in Call.search(base + [('state', '=', 'in_progress')]):
            call.write({'state': 'completed', 'end_time': now,
                        'duration': random.randint(20, 90)})
            if call.dialer_contact_id:
                call.dialer_contact_id.register_result('completed')
            self._sim_release(call.dialer_agent_session_id, 'wrap')

        # 2. Ringing calls resolve: answered? machine? agent free?
        for call in Call.search(base + [('state', '=', 'ringing')]):
            contact = call.dialer_contact_id
            pre = call.dialer_agent_session_id  # progressive pre-assignment
            if random.random() < self.sim_answer_rate:
                if random.random() < self.sim_machine_rate:          # AMD: machine
                    call.write({'state': 'no_answer', 'end_time': now})
                    if contact:
                        contact.register_result('no_answer')
                    self._sim_release(pre, 'ready')
                    continue
                # Human — needs an agent.
                if pre and pre.state == 'on_call':
                    agent = pre
                else:
                    agent = self.session_ids.filtered(lambda s: s.state == 'ready')[:1]
                if agent:
                    # Bind the agent onto the call too (predictive picks here),
                    # so completion/teardown can release them.
                    call.write({'state': 'in_progress',
                                'dialer_agent_session_id': agent.id})
                    agent.write({'state': 'on_call', 'current_call_id': call.id,
                                 'last_state_change': now})
                else:
                    # Human answered but no agent free → abandoned (predictive drop).
                    call.write({'state': 'cancelled', 'end_time': now})
                    if contact:
                        contact.register_result('no_answer')
            else:
                outcome = 'busy' if random.random() < 0.3 else 'no_answer'
                call.write({'state': outcome, 'end_time': now})
                if contact:
                    contact.register_result(outcome)
                self._sim_release(pre, 'ready')

        # 3. Queued → ringing (the "originate" the bridge service would perform).
        Call.search(base + [('state', '=', 'queued')]).write({'state': 'ringing'})

        # 4. Pace: open new lines for this tick.
        self._pace_once()

    @api.model
    def _cron_simulate(self):
        """Cron entry point for dry-run campaigns (safe to leave enabled — only
        touches campaigns with simulate=True)."""
        for c in self.search([('state', '=', 'running'), ('simulate', '=', True)]):
            try:
                c._simulate_tick()
            except Exception:
                _logger.exception("Dialer sim failed for campaign %s", c.id)
