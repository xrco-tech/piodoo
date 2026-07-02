# -*- coding: utf-8 -*-
"""WhatsApp Flow Screen — a single screen within a flow.

A flow is an ordered set of screens. Each screen has its own layout +
component tree. Navigation between screens is driven by the Footer
component's on_click_action on each screen.

Reference: https://developers.facebook.com/docs/whatsapp/flows/reference/flowjson
"""

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


SCREEN_ID_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


class WhatsAppFlowScreen(models.Model):
    _name = 'whatsapp.flow.screen'
    _description = 'WhatsApp Flow Screen'
    _order = 'flow_id, sequence, id'

    flow_id = fields.Many2one(
        'whatsapp.flow', string='Flow', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)

    # Meta requires screen ids in UPPER_SNAKE_CASE (e.g. WELCOME, SUBMIT_OK).
    screen_id = fields.Char(
        string='Screen ID', required=True,
        help="UPPER_SNAKE_CASE identifier used in Flow JSON (e.g. WELCOME, "
             "DETAILS, THANK_YOU). Referenced by Footer navigate actions.",
    )
    title = fields.Char(
        string='Title', required=True,
        help="Visible header at the top of the screen.",
    )

    # Flow lifecycle markers.
    terminal = fields.Boolean(
        string='Terminal',
        help="If True, this is a screen the flow can complete on. Exactly one "
             "screen in the flow must be terminal=True.",
    )
    success = fields.Boolean(
        string='Success',
        help="Marks the screen as the success endpoint (rendered with the "
             "success styling on the user's device).",
    )

    # The "data" block on a screen is a JSON Schema describing dynamic state
    # injected from data_exchange (Phase 3). We store it as a raw text field
    # for now and let advanced authors edit it directly when needed.
    data_schema = fields.Text(
        string='Data Schema',
        help="Optional JSON Schema describing data injected into this screen "
             "from your data_exchange endpoint. Leave empty for static screens.",
    )

    # Layout type — Meta currently only ships SingleColumnLayout, but the
    # field is here so we don't have to migrate when more land.
    layout_type = fields.Selection([
        ('SingleColumnLayout', 'Single Column'),
    ], string='Layout', default='SingleColumnLayout', required=True)

    component_ids = fields.One2many(
        'whatsapp.flow.component', 'screen_id', string='Components',
    )
    component_count = fields.Integer(
        string='Components', compute='_compute_component_count', store=True,
    )

    @api.depends('component_ids')
    def _compute_component_count(self):
        for rec in self:
            rec.component_count = len(rec.component_ids)

    _sql_constraints = [
        ('screen_id_unique_per_flow',
         'UNIQUE(flow_id, screen_id)',
         "Each screen ID must be unique within a flow."),
    ]

    # ── flow_json cascade ────────────────────────────────────────────
    # flow_json on whatsapp.flow is regenerated inside its own write()
    # override. Child records don't naturally trigger that, so a Screen
    # add/edit/delete would leave flow_json out of sync with the
    # structured records. Nudge the parent flow after every mutation.

    def _touch_flows(self):
        flows = self.mapped('flow_id')
        if flows:
            flows.write({})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._touch_flows()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._touch_flows()
        return res

    def unlink(self):
        flows = self.mapped('flow_id')
        res = super().unlink()
        if flows:
            flows.write({})
        return res

    @api.constrains('screen_id')
    def _check_screen_id_format(self):
        for rec in self:
            if not SCREEN_ID_RE.match(rec.screen_id or ''):
                raise ValidationError(
                    f"Screen ID '{rec.screen_id}' must be UPPER_SNAKE_CASE "
                    "(uppercase letters, digits and underscores, starting with a letter). "
                    "Example: WELCOME, USER_DETAILS, THANK_YOU."
                )
