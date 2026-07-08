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

    # ------------------------------------------------------------------
    # Flow diagram — Mermaid source generator
    # ------------------------------------------------------------------
    STEP_SHAPES = {
        'message':        ('[', ']'),
        'menu':           ('{{', '}}'),
        'input':          ('[/', '/]'),
        'condition':      ('{', '}'),
        'action':         ('(', ')'),
        'handoff':        ('([', '])'),
        'llm':            ('[[', ']]'),
        'jump':           ('(', ')'),
        'wait':           ('[', ']'),
        'end':            ('((', '))'),
        'channel_switch': ('[/', '\\]'),
    }
    STEP_CSS = {
        'message':        'message',
        'menu':           'menu',
        'input':          'inputStep',
        'condition':      'condition',
        'action':         'action',
        'handoff':        'handoff',
        'llm':            'llm',
        'jump':           'jump',
        'wait':           'wait',
        'end':            'endStep',
        'channel_switch': 'channelSwitch',
    }

    def _mermaid_escape(self, text):
        if not text:
            return ''
        return (str(text).replace('"', '&quot;')
                          .replace('(', '\\(')
                          .replace(')', '\\)')
                          .replace('|', '\\|')
                          .replace('\n', ' ')
                          .replace('{', '\\{')
                          .replace('}', '\\}')
                          .replace('<', '&lt;'))

    def _short_label(self, step):
        body = (step.body or '').strip()
        preview = body[:40] + ('…' if len(body) > 40 else '')
        return (f'"<b>{self._mermaid_escape(step.name)}</b>'
                f'<br/><small>{self._mermaid_escape(preview)}</small>"')

    def _render_mermaid_source(self, base_url=''):
        """Build a Mermaid flowchart source from bot.step_ids."""
        self.ensure_one()
        lines = ['flowchart TD']
        if self.entry_step_id:
            lines.append(
                f'    ENTRY(("start")):::entryNode --> {self.entry_step_id.id}')

        for step in self.step_ids:
            shape_open, shape_close = self.STEP_SHAPES.get(
                step.kind, ('[', ']'))
            css = self.STEP_CSS.get(step.kind, 'message')
            lines.append(
                f'    {step.id}{shape_open}{self._short_label(step)}{shape_close}'
                f':::{css}')
            if base_url:
                url = f'{base_url}/odoo/action-comm_chatbot.action_comm_bot_step/{step.id}'
                lines.append(f'    click {step.id} "{url}" _blank')

            if step.kind not in ('menu', 'condition', 'end'):
                if step.next_step_id:
                    lines.append(f'    {step.id} --> {step.next_step_id.id}')
            for opt in step.option_ids.sorted('sequence'):
                if opt.next_step_id:
                    label = self._mermaid_escape(opt.label)
                    lines.append(f'    {step.id} -->|{label}| {opt.next_step_id.id}')
            if step.jump_target_step_id:
                lines.append(f'    {step.id} -.->|jump| {step.jump_target_step_id.id}')
            if step.llm_fallback_step_id:
                lines.append(
                    f'    {step.id} -.->|LLM fallback| {step.llm_fallback_step_id.id}')
            if step.on_unsupported_step_id:
                lines.append(
                    f'    {step.id} -.->|unsupported| {step.on_unsupported_step_id.id}')
            if step.input_retry_step_id:
                lines.append(
                    f'    {step.id} -.->|invalid input| {step.input_retry_step_id.id}')
            for target in step.llm_decision_option_ids:
                lines.append(f'    {step.id} ==>|LLM pick| {target.id}')

        if self.on_error_step_id:
            lines.append(
                f'    ERROR(("on error")):::errorNode -.-> '
                f'{self.on_error_step_id.id}')

        lines.extend([
            '    classDef entryNode fill:#37474f,color:#fff,stroke:#263238',
            '    classDef errorNode fill:#ffcdd2,stroke:#c62828',
            '    classDef message fill:#e3f2fd,stroke:#1976d2',
            '    classDef menu fill:#fff3e0,stroke:#f57c00',
            '    classDef inputStep fill:#f3e5f5,stroke:#7b1fa2',
            '    classDef condition fill:#fce4ec,stroke:#c2185b',
            '    classDef action fill:#e0f2f1,stroke:#00796b',
            '    classDef handoff fill:#fff9c4,stroke:#f9a825',
            '    classDef llm fill:#e8f5e9,stroke:#388e3c,stroke-width:2px',
            '    classDef jump fill:#f3e5f5,stroke:#8e24aa',
            '    classDef wait fill:#eceff1,stroke:#546e7a',
            '    classDef endStep fill:#c8e6c9,stroke:#388e3c',
            '    classDef channelSwitch fill:#e1f5fe,stroke:#0288d1',
        ])
        return '\n'.join(lines)

    def action_view_flow_diagram(self):
        """Open the OWL bot flow client action (canvas + simulator)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'comm_chatbot.bot_flow',
            'name': f'Flow: {self.name}',
            'target': 'current',
            'context': {'active_id': self.id, 'default_bot_id': self.id},
        }

    def action_view_flow_diagram_mermaid(self):
        """Fallback: Mermaid HTML page in new tab (kept as legacy option)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/comm_chatbot/bot_flow/{self.id}',
            'target': 'new',
        }
