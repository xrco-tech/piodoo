# -*- coding: utf-8 -*-
# Source: botle_buhle_custom/wizards/consultant_search.py

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging


_logger = logging.getLogger(__name__)


class ConsultantSearchWizard(models.TransientModel):
    _name = "consultant.search.wizard"
    _description = "Consultant Search Wizard"

    search_by = fields.Selection(
        [
            ("sa_id", "ID Number"),
            ("mobile", "Mobile Number"),
            ("name", "Name"),
            ("passport", "Passport"),
            ("sales_force_code", "SFM Code"),
        ],
        string="Search By",
        default="sa_id",
    )
    sa_id = fields.Char("ID Number")
    mobile = fields.Char("Mobile Number")
    name = fields.Char("Name")
    passport = fields.Char("Passport")
    sales_force_code = fields.Char("SFM Code")

    def consultant_search(self):
        ids = []
        _logger.info("Search by %s", self.search_by)

        if self.search_by == "sales_force_code":
            ids = self.env["sf.member"].search_read(
                [("sales_force_code", "=", self.sales_force_code)], ["partner_id"]
            )
            if ids:
                ids = [x["partner_id"][0] for x in ids]

        if self.search_by == "passport":
            ids = self.env["res.partner"].search([("passport", "=", self.passport)]).ids

        if self.search_by == "sa_id":
            ids = self.env["res.partner"].search([("sa_id", "=", self.sa_id)]).ids

        if self.search_by == "name":
            ids = (
                self.env["res.partner"]
                .search(
                    [
                        "|",
                        ("name", "ilike", self.name),
                        ("known_name", "ilike", self.name),
                    ]
                )
                .ids
            )

        if self.search_by == "mobile":
            mobile = self.mobile
            if mobile[:1] == "0" or mobile[:1] == 0:
                mobile = mobile[1:]
            ids = self.env["res.partner"].search([("mobile", "ilike", mobile)]).ids

        tree_view_id = self.env.ref(
            "sales_force_support.res_partner_customer_tree_check"
        ).id
        form_view_id = self.env.ref("sales_force_support.res_partner_customer_view").id

        domain = [("id", "=", ids)]

        action = {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "list"), (form_view_id, "form")],
            "view_mode": "tree,form",
            "name": _("Consultants"),
            "res_model": "res.partner",
            "domain": domain,
            "target": "main",
        }
        return action
