# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CommBotLlmTool(models.Model):
    _name = 'comm.bot.llm.tool'
    _description = 'Tool available to an LLM step'
    _order = 'step_id, sequence'

    step_id = fields.Many2one('comm.bot.step', required=True, ondelete='cascade',
                              index=True,
                              domain="[('kind', '=', 'llm')]")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True,
        help='snake_case identifier the model uses to call this tool.')
    description = fields.Text(required=True,
        help='What the tool does — the model sees this.')
    input_schema = fields.Json(default=dict, required=True,
        help='JSON schema for the tool arguments.')
    executor_type = fields.Selection([
        ('action', 'Odoo action step'),
        ('jump',   'Jump to bot step'),
        ('python', 'Registered Python callable'),
    ], required=True, default='python')
    executor_action_step_id = fields.Many2one('comm.bot.step',
        string='Action step to run',
        domain="[('bot_id', '=', bot_id), ('kind', '=', 'action')]")
    executor_jump_step_id = fields.Many2one('comm.bot.step',
        string='Jump target',
        domain="[('bot_id', '=', bot_id)]")
    executor_python_key = fields.Char(
        help='Key registered via comm_chatbot.runtime.tool_registry.')
    requires_handoff = fields.Boolean(
        help='If True, tool only offered when agent has taken over.')
    result_variable = fields.Char(
        help='Variable name to save tool result in state.')
    log_result_mode = fields.Selection([
        ('full',     'Full (log raw result)'),
        ('redacted', 'Redacted (PII redacted before logging)'),
        ('none',     'None (do not log result)'),
    ], default='redacted', required=True)
    bot_id = fields.Many2one(related='step_id.bot_id', store=True)


class CommBotLlmPromptRevision(models.Model):
    _name = 'comm.bot.llm.prompt.revision'
    _description = 'Version history for LLM system prompts'
    _order = 'step_id, create_date desc'

    step_id = fields.Many2one('comm.bot.step', required=True, ondelete='cascade',
                              index=True,
                              domain="[('kind', '=', 'llm')]")
    body = fields.Text(required=True)
    author_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    notes = fields.Char()
