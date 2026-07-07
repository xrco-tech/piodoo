# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


ENGINE_MODE_SELECTION = [
    ('draft',   'Draft'),
    ('shadow', 'Shadow (log only, do not send)'),
    ('live',   'Live'),
    ('paused', 'Paused'),
]

MISSING_VAR_SELECTION = [
    ('strict',  'Strict — raise on missing'),
    ('lenient', 'Lenient — render as empty'),
    ('debug',   'Debug — render as <<missing>>'),
]


class CommBot(models.Model):
    _name = 'comm.bot'
    _description = 'Communication bot (channel-agnostic script)'
    _order = 'sequence, name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    description = fields.Text()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    engine_mode = fields.Selection(ENGINE_MODE_SELECTION, required=True,
                                   default='draft', tracking=True)

    channel_ids = fields.Many2many('comm.channel', string='Allowed channels',
        help='Channels this bot is allowed to run on.')
    entry_step_id = fields.Many2one('comm.bot.step', string='Entry step',
        domain="[('bot_id', '=', id)]")
    on_error_step_id = fields.Many2one('comm.bot.step', string='On error jump to',
        domain="[('bot_id', '=', id)]",
        help='Where to jump when the renderer or a step errors. If empty, '
             'engine closes the conversation with a generic apology.')
    handoff_team_id = fields.Char(string='Default handoff team',
        help='Team code (points at whatsapp.call.team when comm_whatsapp_calling is installed).')

    default_language = fields.Char(default='en_US', required=True)
    supported_language_ids = fields.Many2many('res.lang',
        string='Supported languages')

    missing_variable_mode = fields.Selection(MISSING_VAR_SELECTION,
        default='lenient', required=True)
    truncation_strategy = fields.Selection([
        ('smart', 'Smart (break at sentence)'),
        ('hard',  'Hard truncate'),
        ('error', 'Error → on_error_step_id'),
    ], default='smart', required=True)

    conversation_timeout_hours = fields.Integer(default=24,
        help='Close abandoned conversations after this many hours of inactivity.')

    # LLM defaults (steps may override)
    default_llm_model = fields.Selection([
        ('claude-opus-4-7',    'Claude Opus 4.7'),
        ('claude-sonnet-4-6',  'Claude Sonnet 4.6'),
        ('claude-haiku-4-5',   'Claude Haiku 4.5'),
    ], default='claude-sonnet-4-6')

    env_variables = fields.Json(default=dict,
        help='Static configuration variables accessible in prompts as {{env.*}}.')

    step_ids = fields.One2many('comm.bot.step', 'bot_id', string='Steps')
    variable_ids = fields.One2many('comm.bot.variable', 'bot_id', string='Variables')
    trigger_ids = fields.One2many('comm.bot.trigger', 'bot_id', string='Triggers')

    step_count = fields.Integer(compute='_compute_step_count')

    @api.depends('step_ids')
    def _compute_step_count(self):
        for bot in self:
            bot.step_count = len(bot.step_ids)

    @api.constrains('engine_mode', 'entry_step_id')
    def _check_live_has_entry(self):
        for bot in self:
            if bot.engine_mode == 'live' and not bot.entry_step_id:
                raise ValidationError(
                    'Bot %s cannot go live without an entry step.' % bot.name)
