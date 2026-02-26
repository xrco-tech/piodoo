# -*- coding: utf-8 -*-
# Source: botle_buhle_custom

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class StatusAuditTrail(models.Model):
    _name = "status.audit.trail"
    _description = "Active Status Trail"

    name = fields.Char("Month")
    emp_id = fields.Many2one("sf.member", "Consultant")

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

    manager_id = fields.Many2one("sf.member", "Manager")
    related_distributor_id = fields.Many2one("sf.member", "Distributor")

    def get_date(self, date):
        month = ""
        year = date.year
        if date.month == 1:
            month = "January"
        if date.month == 2:
            month = "February"
        if date.month == 3:
            month = "March"
        if date.month == 4:
            month = "April"
        if date.month == 5:
            month = "May"
        if date.month == 6:
            month = "June"
        if date.month == 7:
            month = "July"
        if date.month == 8:
            month = "August"
        if date.month == 9:
            month = "September"
        if date.month == 10:
            month = "October"
        if date.month == 11:
            month = "November"
        if date.month == 12:
            month = "December"

        return str(month) + " " + str(year)

    def _update_status_trail(self):
        # sf.member is exclusively for sales force members — no filter needed
        for member in self.env["sf.member"].search([]):
            name = self.get_date(fields.Datetime.now())
            self.create(
                {
                    "name": name,
                    "emp_id": member.id,
                    "active_status": member.active_status,
                    "related_distributor_id": member.related_distributor_id.id,
                    "manager_id": member.manager_id.id,
                }
            )
