# -*- coding: utf-8 -*-
from odoo import models, fields, api


DIRECTION_SELECTION = [
    ('inbound',  'Inbound (from user)'),
    ('outbound', 'Outbound (from bot)'),
]

INTERACTION_STATUS_SELECTION = [
    ('pending',   'Pending'),
    ('rendered',  'Rendered'),
    ('sent',      'Sent'),
    ('delivered', 'Delivered'),
    ('read',      'Read'),
    ('failed',    'Failed'),
    ('received',  'Received'),
]


class CommInteraction(models.Model):
    _name = 'comm.interaction'
    _description = 'One send or receive event'
    _order = 'at desc, id desc'
    _rec_name = 'display_name'

    conversation_id = fields.Many2one('comm.conversation', required=True,
                                       ondelete='cascade', index=True)
    leg_id = fields.Many2one('comm.conversation.leg', index=True)
    channel_id = fields.Many2one('comm.channel', required=True, index=True)
    direction = fields.Selection(DIRECTION_SELECTION, required=True, index=True)
    at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)

    step_id = fields.Many2one('comm.bot.step', index=True,
        help='Bot step that produced or consumed this interaction.')

    raw_body = fields.Text(help='Canonical body pre-rendering.')
    rendered_body = fields.Text(help='Body after channel-specific rendering.')
    input_captured = fields.Char(help='Extracted value for input steps.')

    status = fields.Selection(INTERACTION_STATUS_SELECTION, default='pending',
                              index=True)
    error = fields.Text()
    render_error_type = fields.Char()

    # Source reference (channel-specific)
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)

    # Billing link (uses the existing comm.billing.event model)
    billing_event_id = fields.Many2one('comm.billing.event', index=True,
                                        ondelete='set null')

    # Cost projection at send time (before ledger settles)
    projected_cost_usd = fields.Float(digits=(12, 6))

    # LLM step telemetry
    llm_input_tokens = fields.Integer()
    llm_output_tokens = fields.Integer()
    llm_cache_read_tokens = fields.Integer()
    llm_cache_write_tokens = fields.Integer()
    llm_tool_calls = fields.Integer()
    llm_first_token_latency_ms = fields.Integer()
    llm_model_used = fields.Char()

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('at', 'channel_id.code', 'direction', 'raw_body')
    def _compute_display_name(self):
        for i in self:
            body = (i.raw_body or '')[:40].replace('\n', ' ')
            i.display_name = f'{i.at} [{i.channel_id.code}/{i.direction}] {body}'
