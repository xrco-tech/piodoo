# -*- coding: utf-8 -*-
# Source: botle_buhle_custom
# NOTE: hr.job references replaced with genealogy Selection field values (strings)
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

GENEALOGY_LEVELS = [
    ("Distributor", "Distributor"),
    ("Distributor Partner", "Distributor Partner"),
    ("Prospective Distributor", "Prospective Distributor"),
    ("Manager", "Manager"),
    ("Manager Partner", "Manager Partner"),
    ("Prospective Manager", "Prospective Manager"),
    ("Consultant", "Consultant"),
    ("Potential Consultant", "Potential Consultant"),
    ("Support Office", "Support Office"),
]


class PromotionRules(models.Model):
    _name = "promotion.rules"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Promotion Rules"

    current_genealogy_level = fields.Selection(GENEALOGY_LEVELS, string="Current Genealogy Level", tracking=True)
    next_genealogy_level = fields.Selection(GENEALOGY_LEVELS, string="Next Genealogy Level", tracking=True)
    name = fields.Char("Promotion Rule", compute="_compute_name", store=True)
    sales_month = fields.Integer("Consultant Sales Months")
    own_sales_value = fields.Float("Value of Own Sales")
    team_sales_value = fields.Float("Value of Team Sales")
    team_sales_value_per_promoted_manager = fields.Float(
        "Value of Team Sales per Promoted to Manager"
    )
    retained_consultants = fields.Integer("# Retained Consultants")
    months_retained_consultants = fields.Integer("# Months Retained Consultants")
    months_to_exclude_ids = fields.Many2many(
        "promotion.rules.months", string="Excluded Months"
    )
    promoted_managers = fields.Integer("# Promoted to Manager")
    promoted_managers_moths = fields.Integer(
        "# Active Consultant Months per Promoted to Manager"
    )
    promoted_manager_active_consultants = fields.Integer(
        "# Active Consultants per Promoted to Manager"
    )
    manager_sales_month = fields.Integer("Manager Sales Months")
    promoted_team_sales_month = fields.Integer("# Promoted Team Sales Months")

    @api.depends("current_genealogy_level")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.current_genealogy_level or ""

    @api.model
    def create(self, vals):
        if vals.get("current_genealogy_level") in ["Consultant", "Prospective Manager"]:
            if vals.get("sales_month") == 0:
                raise ValidationError("Consultant Sales Months must not be 0")
        if vals.get("current_genealogy_level") in ["Manager", "Prospective Distributor"]:
            if vals.get("manager_sales_month") == 0:
                raise ValidationError("Manager Sales Months must not be 0")
        return super(PromotionRules, self).create(vals)

    def write(self, vals):
        rec = super(PromotionRules, self).write(vals)
        if self.current_genealogy_level in ["Consultant", "Prospective Manager"]:
            if self.sales_month == 0:
                raise ValidationError("Consultant Sales Months must not be 0")
        if self.current_genealogy_level in ["Manager", "Prospective Distributor"]:
            if self.manager_sales_month == 0:
                raise ValidationError("Manager Sales Months must not be 0")
        return rec


class PromotionRulesMonths(models.Model):
    _name = "promotion.rules.months"
    _description = "Promotion Rules Months"

    name = fields.Char("Month")
    sequence = fields.Integer("Sequence")
