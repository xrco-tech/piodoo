# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/wizards/consultant_move_wizard.py

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class ConsultantMoveWizard(models.TransientModel):
    _name = "consultant.move.wizard"
    _description = "Consultant Move Wizard"

    move_manager_id = fields.Many2one(
        "sf.member", string="Move Consultants To Manager"
    )
    move_date = fields.Date("Move Date")

    move_reason = fields.Selection(
        [
            ("promoted", "Manager Promoted"),
            ("demoted", "Manager Demoted"),
            ("blacklisted", "Manager or Distributor Blacklisted"),
            ("un_blacklisted", "Manager or Distributor Un-Blacklisted"),
            ("deceased", "Manager or Distributor Deceased"),
            ("inactive", "Manager or Distributor Inactive"),
            ("other", "Other"),
        ],
        string="Move Reason",
    )

    def move_consultant(self):
        # move_date = fields.Datetime.now()

        for consultant in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            current_manager_id = consultant.manager_id.id

            consultant_vals = {
                "manager_id": self.move_manager_id.id,
                "previous_manager_id": current_manager_id,
                "move_date": self.move_date,
                "parent_id": self.move_manager_id.id,
                "distribution_id": self.move_manager_id.distribution_id.id,
            }

            _logger.info(
                f"Consultant {consultant.name} ({consultant.sales_force_code}) is being moved to manager {self.move_manager_id.name} ({self.move_manager_id.sales_force_code}). vals: {consultant_vals}"
            )

            consultant.write(consultant_vals)

            consultant_lead_ids = self.env["sf.recruit"].search(
                [
                    ("recruiter_id", "=", consultant.id),
                    ("manager_id", "=", current_manager_id),
                ]
            )
            _logger.info(f"consultant_lead_ids: {consultant_lead_ids.ids}")

            for lead in self.env["sf.recruit"].browse(consultant_lead_ids.ids):
                # Move all linked leads/recruits to selected manager
                lead_vals = {
                    "manager_id": self.move_manager_id.id,
                    "previous_manager_id": current_manager_id,
                    "move_date": self.move_date,
                }

                _logger.info(
                    f"Lead {lead.name} ({lead.sales_force_code}) is being moved to manager {self.move_manager_id.name} ({self.move_manager_id.sales_force_code}). vals: {lead_vals}"
                )

                lead.write(lead_vals)


class ManagerMoveWizard(models.TransientModel):
    _name = "manager.move.wizard"
    _description = "Manager Move Wizard"

    move_distributor_id = fields.Many2one(
        "sf.member", string="Move Consultants To Distributor"
    )
    move_date = fields.Date("Move Date")

    move_reason = fields.Selection(
        [
            ("promoted", "Manager or Distributor Promoted"),
            ("demoted", "Manager or Distributor Demoted"),
            ("blacklisted", "Manager or Distributor Blacklisted"),
            ("un_blacklisted", "Manager or Distributor Un-Blacklisted"),
            ("deceased", "Manager or Distributor Deceased"),
            ("inactive", "Manager or Distributor Inactive"),
            ("other", "Other"),
        ],
        string="Move Reason",
    )

    def move_manager(self):
        # move_date = fields.Datetime.now()
        for manager in self.env["sf.member"].browse(self._context.get("active_ids")):
            current_distributor_id = manager.related_distributor_id.id

            manager_vals = {
                "related_distributor_id": self.move_distributor_id.id,
                "previous_distributor_id": current_distributor_id,
                "move_date": self.move_date,
                "parent_id": self.move_distributor_id.id,
                "distribution_id": self.move_distributor_id.distribution_id.id,
            }

            manager.write(manager_vals)

            _logger.info("child ids %s", manager.child_ids)

            # Update all child employees under this manager
            if manager.child_ids:
                # Move children safely
                for child in manager.child_ids:
                    child.write({
                        "related_distributor_id": self.move_distributor_id.id,
                        "distribution_id": self.move_distributor_id.distribution_id.id,
                    })
