# -*- coding: utf-8 -*-
# Source: bb_payin
from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
from math import ceil


_logger = logging.getLogger(__name__)


class BbPayinHistory(models.Model):
    _name = "bb.payin.history"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In History"

    payin_date = fields.Date("Month/Year")
    employee_id = fields.Many2one("sf.member", string="SFM Name")
    sales_force_code = fields.Char("SFM Code", related="employee_id.sales_force_code")
    current_genealogy = fields.Selection(
        [
            ("Distributor", "Distributor"),
            ("Distributor Partner", "Distributor Partner"),
            ("Prospective Distributor", "Prospective Distributor"),
            ("Manager", "Manager"),
            ("Manager Partner", "Manager Partner"),
            ("Prospective Manager", "Prospective Manager"),
            ("Consultant", "Consultant"),
            ("Potential Consultant", "Potential Consultant"),
            ("Support Office", "Support Office"),
        ],
        string="Current Genealogy",
    )
    manager_code = fields.Char(string="Current Manager Code")
    distributor_code = fields.Char(string="Current Distributor Code")
    active_status = fields.Selection(
        [
            ("potential_consultant", "Potential Consultant"),
            ("pay_in_sheet_pending", "Pay-In Sheet Pending"),
            ("active1", "Active 1"),
            ("active2", "Active 2"),
            ("active3", "Active 3"),
            ("active4", "Active 4"),
            ("active5", "Active 5"),
            ("active6", "Active 6"),
            ("inactive12", "Inactive 12"),
            ("inactive18", "Inactive 18"),
            ("suspended", "Suspended"),
            ("blacklisted", "Internally Blacklisted"),
        ],
        string="Active Status",
        tracking=True,
    )
    promoted_this_month = fields.Boolean("Promoted this month?")
    personal_bbb_sale = fields.Float("Personal Sales (BBB) this month")
    personal_puer_sale = fields.Float("Personal Sales (Puer) this month")
    promoted_by = fields.Many2one("sf.member", "Promoted By")
    personal_sales_promotion = fields.Boolean("Personal Sales Promotion Flag")
    active_sfm_this_month = fields.Integer("# Active SFM this month")
    active_sfm_promotion = fields.Boolean("# Active SFM Promotion Flag")
    team_sales_promotion = fields.Boolean("Team Sales Promotion Flag")
    manager_id = fields.Many2one("sf.member", string="Manager Name")
    name = fields.Char("Name", related="employee_id.name")
    team_bbb_sales = fields.Float("Team Sales (BBB)")
    team_puer_sales = fields.Float("Team Sales (Puer)")
    team_promoted = fields.Integer("# Team Promoted")
    team_promoted_promotion = fields.Boolean("Team Promoted Promotion Flag")
    manager_promote_avtive_consultants = fields.Boolean(
        "# Manager Promoted: Active Consultants Flag"
    )
    manger_promoted_sales_above = fields.Boolean(
        "# Manager Promoted: Sales above threshold Promotion Flag"
    )
    pbm_promoted_avtive_consultants = fields.Integer(
        "# PBM's Promoted Managers: Active Consultants"
    )
    pbm_promoted_managers_active_promotion = fields.Boolean(
        "PBM's Promoted Managers: Active Promotion Flag"
    )
    pbm_promoted_managers_team_sales_above = fields.Integer(
        "# PBM's Promoted Managers: Team Sales above threshold"
    )
    pbm_team_sales_above = fields.Boolean("PBM's Team Sales above threshold Flag")
    total_team_sales = fields.Float(
        "Total Team Sales", compute="_comput_total_team_sales"
    )
    total_personal_sales = fields.Float(
        "Total Personal Sales", compute="_comput_total_personal_sales"
    )
    active_80 = fields.Boolean("80% Active SFM Target Flag")
    team_80 = fields.Boolean("80% Team Sales Target Flag")
    personal_80 = fields.Boolean("80% Personal Sales Target Flag")
    changed = fields.Boolean("Pay-In Changed")

    def _comput_total_team_sales(self):
        for record in self:
            record.total_team_sales = record.team_bbb_sales + record.team_puer_sales

    def _comput_total_personal_sales(self):
        for record in self:
            record.total_personal_sales = (
                record.personal_bbb_sale + record.personal_puer_sale
            )
