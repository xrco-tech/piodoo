# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api


CONVERSATION_STATE_SELECTION = [
    ('open',     'Open'),
    ('waiting',  'Waiting for user'),
    ('handoff',  'Handed off to agent'),
    ('closed',   'Closed'),
    ('timeout',  'Timed out'),
    ('error',    'Errored'),
]


class CommConversation(models.Model):
    _name = 'comm.conversation'
    _description = 'Cross-channel conversation'
    _order = 'last_activity_at desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(compute='_compute_name', store=True)
    partner_id = fields.Many2one('res.partner', required=True, index=True,
                                 tracking=True)
    bot_id = fields.Many2one('comm.bot', index=True, tracking=True,
                             help='Currently active bot.')
    current_step_id = fields.Many2one('comm.bot.step', tracking=True)
    primary_channel_id = fields.Many2one('comm.channel', index=True,
        help='Channel the conversation is currently on.')

    state = fields.Json(default=dict,
        help='Session variables — populated by input, action, and llm steps.')
    lifecycle_state = fields.Selection(CONVERSATION_STATE_SELECTION,
        default='open', required=True, index=True, tracking=True)

    opened_at = fields.Datetime(default=fields.Datetime.now, required=True)
    last_activity_at = fields.Datetime(default=fields.Datetime.now, required=True,
                                       index=True)
    timeout_at = fields.Datetime(index=True,
        help='Auto-close after this datetime with lifecycle_state=timeout.')
    closed_at = fields.Datetime()
    outcome = fields.Char(help='Free-form tag set by end steps.')

    assigned_agent_id = fields.Many2one('res.users', tracking=True)
    assigned_team_code = fields.Char()

    campaign_id = fields.Char(index=True,
        help='Optional campaign attribution.')

    leg_ids = fields.One2many('comm.conversation.leg', 'conversation_id')
    interaction_ids = fields.One2many('comm.interaction', 'conversation_id')

    # Denormalized counters for lists
    interaction_count = fields.Integer(compute='_compute_interaction_count')

    @api.depends('interaction_ids')
    def _compute_interaction_count(self):
        for c in self:
            c.interaction_count = len(c.interaction_ids)

    @api.depends('partner_id.name', 'bot_id.name', 'opened_at')
    def _compute_name(self):
        for c in self:
            who = c.partner_id.name or '?'
            bot = c.bot_id.name or '(no bot)'
            when = c.opened_at.strftime('%Y-%m-%d %H:%M') if c.opened_at else ''
            c.name = f'{who} — {bot} ({when})'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'timeout_at' not in vals:
                hours = 24
                if vals.get('bot_id'):
                    bot = self.env['comm.bot'].browse(vals['bot_id'])
                    hours = bot.conversation_timeout_hours or 24
                vals['timeout_at'] = fields.Datetime.now() + timedelta(hours=hours)
        return super().create(vals_list)

    def touch(self):
        """Bump last_activity_at and extend timeout."""
        for c in self:
            hours = c.bot_id.conversation_timeout_hours or 24
            c.write({
                'last_activity_at': fields.Datetime.now(),
                'timeout_at': fields.Datetime.now() + timedelta(hours=hours),
            })

    def close(self, outcome=None, state='closed'):
        for c in self:
            c.write({
                'lifecycle_state': state,
                'closed_at': fields.Datetime.now(),
                'outcome': outcome or c.outcome,
            })
            # Close all open legs
            c.leg_ids.filtered(lambda l: not l.closed_at).close()

    @api.model
    def cron_close_stale(self):
        """Called by ir.cron — closes conversations past timeout_at."""
        now = fields.Datetime.now()
        stale = self.search([
            ('lifecycle_state', 'in', ('open', 'waiting')),
            ('timeout_at', '<', now),
        ], limit=500)
        for c in stale:
            c.close(outcome='timeout', state='timeout')

    @api.model
    def find_or_open(self, partner, bot, channel, external_session_id=None):
        """Match an existing open conversation for this partner+bot, or open a new
        one. Legs are created lazily by the caller."""
        existing = self.search([
            ('partner_id', '=', partner.id),
            ('bot_id', '=', bot.id),
            ('lifecycle_state', 'in', ('open', 'waiting')),
        ], limit=1, order='last_activity_at desc')
        if existing:
            existing.touch()
            return existing
        return self.create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id if bot.entry_step_id else False,
        })


class CommConversationLeg(models.Model):
    _name = 'comm.conversation.leg'
    _description = 'One channel-slice of a conversation'
    _order = 'opened_at desc, id desc'

    conversation_id = fields.Many2one('comm.conversation', required=True,
                                       ondelete='cascade', index=True)
    channel_id = fields.Many2one('comm.channel', required=True, index=True)
    external_session_id = fields.Char(index=True,
        help='Channel-specific session ID (WA wa_id, USSD session_id, voice call ID).')
    opened_at = fields.Datetime(default=fields.Datetime.now, required=True)
    closed_at = fields.Datetime(index=True)

    # Source reference (channel-specific)
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)

    def close(self):
        for l in self:
            if not l.closed_at:
                l.closed_at = fields.Datetime.now()

    @api.model
    def find_for_source(self, source_model, source_id):
        return self.search([
            ('source_model', '=', source_model),
            ('source_id', '=', source_id),
        ], limit=1)
