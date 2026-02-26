# -*- coding: utf-8 -*-
# Source: replaces hr.recruitment.stage for the Sales Force recruit pipeline
# Changes from original:
#   - New standalone model (no _inherit from hr.recruitment.stage)
#   - hired_stage renamed to joined_stage
#   - create_employee renamed to create_member
#   - job_ids (Many2many to hr.job) removed — stages apply to all sf.recruit records

from odoo import models, fields, api, _

import logging
_logger = logging.getLogger(__name__)


class SfRecruitStage(models.Model):
    _name = "sf.recruit.stage"
    _description = "Sales Force Recruit Stage"
    _order = "sequence, name"

    name = fields.Char("Stage Name", required=True, translate=True)
    sequence = fields.Integer("Sequence", default=10)
    fold = fields.Boolean(
        "Folded in Kanban",
        default=False,
        help="Folded stages are collapsed in the Kanban view.",
    )
    joined_stage = fields.Boolean(
        "Joined Stage",
        default=False,
        help="If set, reaching this stage means the recruit has joined as a Sales Force Member.",
    )
    create_member = fields.Boolean(
        "Create Sales Force Member",
        default=False,
        help="Automatically create an sf.member record when this stage is reached.",
    )
    sales_force = fields.Boolean("Sales Force", default=True)
    active = fields.Boolean("Active", default=True)

    # Kanban state legend labels (mirrors Odoo recruitment pattern)
    legend_blocked = fields.Char(
        "Kanban State Blocked",
        default="Blocked",
        translate=True,
    )
    legend_done = fields.Char(
        "Kanban State Ready for Next Stage",
        default="Ready for Next Stage",
        translate=True,
    )
    legend_normal = fields.Char(
        "Kanban State In Progress",
        default="In Progress",
        translate=True,
    )
