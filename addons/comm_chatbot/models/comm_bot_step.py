# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


STEP_KIND_SELECTION = [
    ('message',        'Message (send + advance)'),
    ('menu',           'Menu (send options + wait for choice)'),
    ('input',          'Input (prompt + capture value)'),
    ('condition',      'Condition (branch on expression)'),
    ('action',         'Action (executor: HTTP / Odoo / python)'),
    ('handoff',        'Handoff to agent / team'),
    ('llm',            'LLM (first-class AI step)'),
    ('jump',           'Jump (goto another step / bot)'),
    ('wait',           'Wait (delay / scheduled)'),
    ('end',            'End (close conversation)'),
    ('channel_switch', 'Channel switch (move to a different channel)'),
]

INPUT_TYPE_SELECTION = [
    ('text',   'Free text'),
    ('number', 'Number'),
    ('date',   'Date'),
    ('choice', 'Choice (from options)'),
    ('media',  'Media upload'),
    ('email',  'Email address'),
    ('phone',  'Phone number'),
]

LLM_OUTPUT_MODE_SELECTION = [
    ('freeform',   'Freeform (send response as message body)'),
    ('structured', 'Structured (save JSON to variable)'),
    ('decision',   'Decision (pick next step from allowed set)'),
]


class CommBotStep(models.Model):
    _name = 'comm.bot.step'
    _description = 'Bot step (flow node)'
    _order = 'bot_id, sequence, id'
    _rec_name = 'display_name'

    bot_id = fields.Many2one('comm.bot', required=True, ondelete='cascade',
                             index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True,
        help='Human-readable identifier used in flow graph and jumps.')
    kind = fields.Selection(STEP_KIND_SELECTION, required=True, default='message',
                            index=True)

    # Canonical body (Mustache templated)
    body = fields.Text()
    body_translation_ids = fields.One2many('comm.bot.step.translation',
                                           'step_id', string='Translations')

    # Optional condition to skip step entirely
    guard_expression = fields.Char(
        help='If set, step is skipped when this expression evaluates falsy.')

    # Input capture
    input_type = fields.Selection(INPUT_TYPE_SELECTION,
        help='For kind=input: what to capture.')
    input_save_to = fields.Char(
        help='Variable name to store captured input in state.')
    input_validation_regex = fields.Char()
    input_retry_step_id = fields.Many2one('comm.bot.step',
        string='Retry step on invalid input',
        domain="[('bot_id', '=', bot_id)]")

    # Condition
    condition_expression = fields.Char(
        help='For kind=condition: expression evaluated to pick branch.')

    # Action
    action_executor = fields.Selection([
        ('http',    'HTTP webhook'),
        ('odoo',    'Odoo model call'),
        ('python',  'Registered Python callable'),
    ])
    action_config = fields.Json(default=dict,
        help='Executor-specific config (URL/method/headers for http, '
             'model/method/args for odoo, callable_key for python).')
    action_save_to = fields.Char(
        help='Variable name to store action result in state.')

    # Handoff
    handoff_team_id = fields.Char(help='Target team code. If empty, uses bot default.')
    handoff_message = fields.Char(default='Connecting you to an agent...')

    # LLM (see comm_bot_llm.py for tools)
    llm_model = fields.Selection([
        ('claude-opus-4-7',   'Claude Opus 4.7'),
        ('claude-sonnet-4-6', 'Claude Sonnet 4.6'),
        ('claude-haiku-4-5',  'Claude Haiku 4.5'),
    ], help='Model for kind=llm. Falls back to bot.default_llm_model if empty.')
    llm_fallback_model = fields.Selection([
        ('claude-opus-4-7',   'Claude Opus 4.7'),
        ('claude-sonnet-4-6', 'Claude Sonnet 4.6'),
        ('claude-haiku-4-5',  'Claude Haiku 4.5'),
    ])
    llm_system_prompt = fields.Text(
        help='Templated system prompt (Mustache {{state.*}} substitution).')
    llm_temperature = fields.Float(default=0.5)
    llm_max_tokens = fields.Integer(default=1024)
    llm_max_duration_sec = fields.Integer(default=30)
    llm_max_tool_iterations = fields.Integer(default=5)
    llm_max_cost_usd = fields.Float(default=0.10, digits=(8, 4))
    llm_output_mode = fields.Selection(LLM_OUTPUT_MODE_SELECTION,
                                       default='freeform')
    llm_output_schema = fields.Json(default=dict,
        help='For structured mode: JSON schema for expected shape.')
    llm_output_save_to = fields.Char(
        help='Variable name to store structured output.')
    llm_decision_option_ids = fields.Many2many('comm.bot.step',
        'comm_bot_step_llm_decision_options_rel',
        'source_id', 'target_id',
        string='Allowed decision targets',
        domain="[('bot_id', '=', bot_id)]",
        help='For decision mode: allowed next steps.')
    llm_include_history = fields.Boolean(default=True)
    llm_history_turns = fields.Integer(default=10)
    llm_fallback_step_id = fields.Many2one('comm.bot.step',
        string='LLM fallback step',
        domain="[('bot_id', '=', bot_id)]",
        help='Jump target on refusal / timeout / error.')
    llm_content_filter = fields.Selection([
        ('none',   'None'),
        ('basic',  'Basic (regex + Haiku classifier)'),
        ('strict', 'Strict (heavy pre-check)'),
    ], default='basic')
    llm_cache_breakpoint = fields.Boolean(default=True,
        help='Enable Anthropic prompt caching after system prompt.')
    llm_tool_ids = fields.One2many('comm.bot.llm.tool', 'step_id',
                                   string='Available tools')

    # Wait
    wait_seconds = fields.Integer(default=0,
        help='For kind=wait: seconds to wait. Ignored if wait_until_variable set.')
    wait_until_variable = fields.Char(
        help='State variable holding an ISO datetime to wait until.')

    # Jump
    jump_target_step_id = fields.Many2one('comm.bot.step',
        string='Jump to step',
        domain="[('bot_id', '=', bot_id)]")
    jump_target_bot_id = fields.Many2one('comm.bot',
        string='Jump to bot (starts fresh)')

    # Channel switch
    channel_switch_target_id = fields.Many2one('comm.channel')
    channel_switch_message = fields.Char(
        default="Let's continue on {{channel.name}}. I'll message you there.")

    # End
    end_outcome = fields.Char(help='Outcome tag when this end step fires.')

    # Fall-through
    next_step_id = fields.Many2one('comm.bot.step',
        string='Default next step',
        domain="[('bot_id', '=', bot_id)]")

    # Rendering
    truncation_strategy = fields.Selection([
        ('inherit', 'Inherit from bot'),
        ('smart',   'Smart'),
        ('hard',    'Hard'),
        ('error',   'Error'),
    ], default='inherit')
    on_unsupported_step_id = fields.Many2one('comm.bot.step',
        string='If channel unsupported, jump to',
        domain="[('bot_id', '=', bot_id)]",
        help='For steps like media upload on USSD — where to go if channel '
             'cannot render this step.')

    media_ids = fields.One2many('comm.bot.step.media', 'step_id',
                                string='Media attachments')
    option_ids = fields.One2many('comm.bot.step.option', 'step_id',
                                 string='Menu options')
    channel_override_ids = fields.One2many('comm.bot.step.channel.override',
                                           'step_id', string='Channel overrides')
    metadata = fields.Json(default=dict)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('name', 'kind', 'bot_id.name')
    def _compute_display_name(self):
        for step in self:
            step.display_name = f'[{step.kind}] {step.name}'

    @api.constrains('bot_id', 'name')
    def _check_unique_name_per_bot(self):
        for step in self:
            dupes = self.search([
                ('bot_id', '=', step.bot_id.id),
                ('name', '=', step.name),
                ('id', '!=', step.id),
            ])
            if dupes:
                raise ValidationError(
                    f'Step name "{step.name}" already used in bot {step.bot_id.name}.')


class CommBotStepOption(models.Model):
    _name = 'comm.bot.step.option'
    _description = 'Menu option / choice on a bot step'
    _order = 'step_id, sequence'

    step_id = fields.Many2one('comm.bot.step', required=True, ondelete='cascade',
                              index=True)
    bot_id = fields.Many2one(related='step_id.bot_id', store=True)
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True, help='What the user sees.')
    value = fields.Char(help='What is stored in state when picked (defaults to label).')
    next_step_id = fields.Many2one('comm.bot.step',
        string='Next step',
        domain="[('bot_id', '=', bot_id)]")
    condition_expression = fields.Char(
        help='If set, option only shown when this evaluates truthy.')
    is_default = fields.Boolean(
        help='Picked when user input matches nothing else.')


class CommBotStepChannelOverride(models.Model):
    _name = 'comm.bot.step.channel.override'
    _description = 'Per-channel override for a bot step'
    _order = 'step_id, channel_id'

    step_id = fields.Many2one('comm.bot.step', required=True, ondelete='cascade',
                              index=True)
    channel_id = fields.Many2one('comm.channel', required=True, index=True)
    body_override = fields.Text(
        help='Replaces step.body on this channel. Leave empty to keep default.')
    media_override_ids = fields.One2many('comm.bot.step.media',
                                         'channel_override_id',
                                         string='Media overrides')
    hide = fields.Boolean(
        help='If True, step is skipped entirely on this channel — engine jumps to next.')

    _sql_constraints = [
        ('step_channel_uniq', 'unique(step_id, channel_id)',
         'Only one override per (step, channel).'),
    ]


class CommBotStepMedia(models.Model):
    _name = 'comm.bot.step.media'
    _description = 'Media attached to a bot step'
    _order = 'sequence'

    step_id = fields.Many2one('comm.bot.step', ondelete='cascade', index=True)
    channel_override_id = fields.Many2one('comm.bot.step.channel.override',
                                          ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('image',    'Image'),
        ('video',    'Video'),
        ('audio',    'Audio'),
        ('document', 'Document'),
    ], required=True)
    url = fields.Char(help='Public URL. Alternative to attachment_id.')
    attachment_id = fields.Many2one('ir.attachment')
    alt_text = fields.Char(
        help='Fallback text when channel cannot render media (voice TTS uses this).')


class CommBotStepTranslation(models.Model):
    _name = 'comm.bot.step.translation'
    _description = 'Per-language translation of a bot step body'
    _order = 'step_id, language'

    step_id = fields.Many2one('comm.bot.step', required=True, ondelete='cascade')
    language = fields.Char(required=True, help='e.g. en_US, af_ZA, zu_ZA')
    body = fields.Text(required=True)

    _sql_constraints = [
        ('step_language_uniq', 'unique(step_id, language)',
         'Only one translation per (step, language).'),
    ]
