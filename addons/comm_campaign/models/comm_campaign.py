# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


CAMPAIGN_STATE_SELECTION = [
    ('draft',      'Draft'),
    ('scheduled',  'Scheduled'),
    ('running',    'Running'),
    ('paused',     'Paused'),
    ('completed',  'Completed'),
    ('suspended',  'Suspended (error)'),
]

AUDIENCE_MODE_SELECTION = [
    ('static',    'Static (snapshot at schedule time)'),
    ('dynamic',   'Dynamic (re-evaluate each batch)'),
    ('streaming', 'Streaming (event-triggered)'),
]

ATTRIBUTION_MODEL_SELECTION = [
    ('last',   'Last-touch (default)'),
    ('first',  'First-touch'),
    ('linear', 'Linear (evenly split)'),
]


class CommCampaign(models.Model):
    _name = 'comm.campaign'
    _description = 'Communication campaign'
    _order = 'schedule_at desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    description = fields.Text()
    state = fields.Selection(CAMPAIGN_STATE_SELECTION, default='draft',
                             required=True, tracking=True, index=True)
    owner_id = fields.Many2one('res.users', default=lambda self: self.env.user,
                               tracking=True)

    # What runs
    bot_id = fields.Many2one('comm.bot', required=True, tracking=True,
        help='The bot script that runs for each recipient.')
    variant_ids = fields.One2many('comm.campaign.variant', 'campaign_id',
                                   string='A/B Variants')

    # Audience
    audience_mode = fields.Selection(AUDIENCE_MODE_SELECTION, default='static',
                                     required=True)
    audience_domain = fields.Char(default='[]',
        help='Odoo domain on res.partner. Evaluated per audience_mode.')
    snapshot_ids = fields.One2many('comm.campaign.audience.snapshot',
                                    'campaign_id', string='Audience snapshot')
    audience_count = fields.Integer(compute='_compute_audience_count')

    # Channels
    channel_priority_ids = fields.Many2many('comm.channel',
        string='Channel priority',
        help='Ordered by sequence; first channel where partner is reachable wins.')
    purpose = fields.Selection([
        ('marketing',     'Marketing'),
        ('transactional', 'Transactional'),
        ('service',       'Service'),
    ], default='marketing', required=True)

    # Scheduling
    schedule_at = fields.Datetime(default=fields.Datetime.now, tracking=True)
    expires_at = fields.Datetime()
    throttle_per_minute = fields.Integer(default=60,
        help='Max sends per minute for this campaign.')

    # Quiet hours + timezone
    respect_quiet_hours = fields.Boolean(default=True)
    partner_timezone_source = fields.Selection([
        ('partner',  'Partner tz'),
        ('company',  'Company tz'),
        ('utc',      'UTC'),
    ], default='partner')
    send_on_weekends = fields.Boolean(default=True)

    # Opt-out handling
    opt_out_keywords = fields.Char(default='STOP,END,UNSUBSCRIBE,CANCEL',
        help='Comma-separated keywords that trigger opt-out on reply.')

    # Budget
    budget_cap_local = fields.Float(digits=(12, 2))
    budget_currency_id = fields.Many2one('res.currency',
        default=lambda self: self.env.company.currency_id)
    budget_soft_threshold_pct = fields.Integer(default=80,
        help='Notify owner when spend crosses this % of cap.')
    hard_stop_at_cap = fields.Boolean(default=False,
        help='If True, stop sending when 100%% of budget is used.')
    budget_warning_sent = fields.Boolean(readonly=True)
    budget_exceeded_notified = fields.Boolean(readonly=True)

    # Attribution
    attribution_window_hours = fields.Integer(default=72)
    attribution_model = fields.Selection(ATTRIBUTION_MODEL_SELECTION,
                                          default='last')

    # Runtime denorm
    send_ids = fields.One2many('comm.campaign.send', 'campaign_id',
                                string='Sends')
    total_sends = fields.Integer(compute='_compute_totals')
    successful_sends = fields.Integer(compute='_compute_totals')
    failed_sends = fields.Integer(compute='_compute_totals')
    total_cost_usd = fields.Float(compute='_compute_totals', digits=(12, 4))
    total_cost_local = fields.Float(compute='_compute_totals', digits=(12, 2))
    conversion_count = fields.Integer(compute='_compute_totals')

    @api.depends('send_ids.status', 'send_ids.billed_usd', 'send_ids.billed_local',
                 'send_ids.conversation_id.outcome')
    def _compute_totals(self):
        for c in self:
            c.total_sends = len(c.send_ids)
            c.successful_sends = len(c.send_ids.filtered(
                lambda s: s.status in ('sent', 'delivered')))
            c.failed_sends = len(c.send_ids.filtered(
                lambda s: s.status == 'failed'))
            c.total_cost_usd = sum(c.send_ids.mapped('billed_usd'))
            c.total_cost_local = sum(c.send_ids.mapped('billed_local'))
            c.conversion_count = len(c.send_ids.filtered(
                lambda s: s.conversion_registered))

    @api.depends('snapshot_ids', 'audience_domain', 'audience_mode')
    def _compute_audience_count(self):
        for c in self:
            if c.audience_mode == 'static' and c.snapshot_ids:
                c.audience_count = len(c.snapshot_ids)
            else:
                try:
                    domain = eval(c.audience_domain or '[]',
                                  {'__builtins__': {}}, {})
                    c.audience_count = self.env['res.partner'].search_count(domain)
                except Exception:
                    c.audience_count = 0

    # ---------- Lifecycle ----------
    def action_schedule(self):
        for c in self:
            if not c.bot_id or not c.bot_id.entry_step_id:
                raise UserError('Bot must have an entry step before scheduling.')
            if not c.channel_priority_ids:
                raise UserError('Set at least one channel in priority list.')
            if c.audience_mode == 'static':
                c._materialize_snapshot()
            c.state = 'scheduled'
        return True

    def action_run_now(self):
        self.write({'schedule_at': fields.Datetime.now()})
        self.action_schedule()

    def action_pause(self):
        self.write({'state': 'paused'})

    def action_resume(self):
        self.filtered(lambda c: c.state == 'paused').write({'state': 'running'})

    def _materialize_snapshot(self):
        Snapshot = self.env['comm.campaign.audience.snapshot']
        for c in self:
            try:
                domain = eval(c.audience_domain or '[]',
                              {'__builtins__': {}}, {})
            except Exception as e:
                raise ValidationError(f'Invalid audience_domain: {e}')
            partners = self.env['res.partner'].search(domain)
            Snapshot.search([('campaign_id', '=', c.id)]).unlink()
            for p in partners:
                Snapshot.create({'campaign_id': c.id, 'partner_id': p.id})

    # ---------- Cron ----------
    @api.model
    def cron_run(self):
        """Process due campaigns."""
        now = fields.Datetime.now()
        due = self.search([
            ('state', 'in', ('scheduled', 'running')),
            ('schedule_at', '<=', now),
            '|', ('expires_at', '=', False), ('expires_at', '>=', now),
        ])
        for campaign in due:
            campaign._process_batch()

    def _process_batch(self):
        """Process one batch of sends respecting throttle_per_minute."""
        self.ensure_one()
        if self.state == 'scheduled':
            self.state = 'running'
        Send = self.env['comm.campaign.send']

        # Determine batch size — throttle_per_minute / 4 = 15s worth
        batch = max(1, int(self.throttle_per_minute / 4))

        # Materialise sends from audience/snapshot if not already
        self._enqueue_sends(batch)

        # Process queued sends
        queued = Send.search([
            ('campaign_id', '=', self.id),
            ('status', '=', 'queued'),
            '|', ('scheduled_at', '=', False), ('scheduled_at', '<=', fields.Datetime.now()),
        ], limit=batch)
        for send in queued:
            send._process()

        # Check completion
        remaining = Send.search_count([
            ('campaign_id', '=', self.id),
            ('status', 'in', ('queued', 'deferred')),
        ])
        if remaining == 0 and self.audience_count == Send.search_count([
                ('campaign_id', '=', self.id)]):
            self.state = 'completed'

    def _enqueue_sends(self, batch):
        """For audience partners without a comm.campaign.send row, create one."""
        Send = self.env['comm.campaign.send']
        if self.audience_mode == 'static':
            partners = self.snapshot_ids.mapped('partner_id')
        else:
            try:
                domain = eval(self.audience_domain or '[]',
                              {'__builtins__': {}}, {})
            except Exception:
                return
            partners = self.env['res.partner'].search(domain, limit=batch * 10)

        existing_partner_ids = set(Send.search([
            ('campaign_id', '=', self.id),
        ]).mapped('partner_id.id'))
        new_partners = partners.filtered(lambda p: p.id not in existing_partner_ids)
        for p in new_partners[:batch * 5]:
            variant = self._pick_variant(p) if self.variant_ids else False
            Send.create({
                'campaign_id': self.id,
                'partner_id': p.id,
                'variant_id': variant.id if variant else False,
            })

    def _pick_variant(self, partner):
        """Deterministic weighted variant assignment."""
        import hashlib
        variants = self.variant_ids.sorted('id')
        total_weight = sum(v.weight for v in variants)
        if total_weight == 0:
            return variants[:1]
        h = int(hashlib.sha256(f'{partner.id}|{self.id}'.encode()).hexdigest(), 16)
        bucket = h % total_weight
        running = 0
        for v in variants:
            running += v.weight
            if bucket < running:
                return v
        return variants[-1]

    # ---------- Budget check ----------
    def _check_budget(self, projected_cost_local=0.0):
        """Return one of: 'ok', 'warn', 'exceeded'."""
        self.ensure_one()
        if not self.budget_cap_local:
            return 'ok'
        current_plus_projected = self.total_cost_local + projected_cost_local
        pct = (current_plus_projected / self.budget_cap_local) * 100
        if pct >= 100:
            return 'exceeded'
        if pct >= (self.budget_soft_threshold_pct or 80):
            return 'warn'
        return 'ok'

    def _notify_budget(self, status):
        """Post activity/message to owner."""
        self.ensure_one()
        if status == 'warn' and not self.budget_warning_sent:
            self.message_post(
                body=f'Campaign at {self.budget_soft_threshold_pct}% of budget '
                     f'({self.total_cost_local:.2f} / {self.budget_cap_local:.2f})',
                partner_ids=[self.owner_id.partner_id.id] if self.owner_id else [],
            )
            self.budget_warning_sent = True
        elif status == 'exceeded' and not self.budget_exceeded_notified:
            self.message_post(
                body=f'Campaign exceeded budget cap '
                     f'({self.total_cost_local:.2f} / {self.budget_cap_local:.2f})',
                partner_ids=[self.owner_id.partner_id.id] if self.owner_id else [],
            )
            self.budget_exceeded_notified = True
