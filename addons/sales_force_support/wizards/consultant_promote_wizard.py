# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/wizards/consultant_promote_wizard.py

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class PotentialConsultantPromoteWizard(models.TransientModel):
    _name = "potential_consultant.promotion.wizard"
    _description = "Potential Consultant Promotion Wizard"

    activation_reason = fields.Selection(
        [("first_sale", "Made First Sale"), ("other", "Other")],
        string="Activation Reason",
    )

    # action to promote consultant to manager
    def promote_potential_consultant(self):
        for consultant in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            consultant_vals = {
                "genealogy": "consultant",
                "active_status": "active1",
            }

            consultant.write(consultant_vals)


class ConsultantPromoteWizard(models.TransientModel):
    _name = "consultant.promotion.wizard"
    _description = "Consultant Promotion Wizard"

    promoter_id = fields.Many2one("sf.member", string="Promoted By")
    promotion_date = fields.Date("Promotion Date")
    promotion_effective_date = fields.Date("Promotion Effective Date")

    promotion_reason = fields.Selection(
        [("promoted", "Fulfilled Promotion Criteria"), ("other", "Other")],
        string="Promotion Reason",
    )

    # action to promote consultant to manager
    def promote_consultant(self):
        # promotion_date = fields.Datetime.now()
        # promotion_effective_date = promotion_date.replace(day=1) + relativedelta(months=+1)

        for consultant in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            current_manager_id = consultant.manager_id.id

            consultant_vals = {
                "genealogy": "prospective_manager",
                "previous_genealogy": "consultant",
                "promotion_date": self.promotion_date,
                "promotion_effective_date": self.promotion_effective_date,
                "promoter_id": self.promoter_id.id,
                "related_prospective_manager_id": consultant.id,
            }

            consultant.write(consultant_vals)

            consultant_records = []

            # get consultants recruited by new prospective manager
            related_prospective_manager_id = consultant.id
            recruited_by_consultant_ids = self.env["sf.member"].search(
                [
                    ("genealogy", "in", ["consultant", "potential_consultant"]),
                    ("recruiter_id", "=", related_prospective_manager_id),
                    ("manager_id", "=", current_manager_id),
                ]
            )

            if recruited_by_consultant_ids:
                consultant_records = recruited_by_consultant_ids.ids

            for recruited_by_consultant in self.env["sf.member"].browse(
                recruited_by_consultant_ids.ids
            ):
                recruited_by_consultant_vals = {
                    "related_prospective_manager_id": related_prospective_manager_id,
                }

                recruited_by_consultant.write(recruited_by_consultant_vals)

            consultant_records.append(consultant.id)

            recruited_by_lead_ids = self.env["sf.recruit"].search(
                [
                    ("recruiter_id", "in", consultant_records),
                    ("manager_id", "=", current_manager_id),
                ]
            )

            for recruited_by_lead in self.env["sf.recruit"].browse(
                recruited_by_lead_ids.ids
            ):
                recruited_by_lead_vals = {
                    "related_prospective_manager_id": related_prospective_manager_id,
                }

                recruited_by_lead.write(recruited_by_lead_vals)


class ProspectiveManagerPromoteWizard(models.TransientModel):
    _name = "prospective_manager.promotion.wizard"
    _description = "Prospective Manager Promotion Wizard"

    promoter_id = fields.Many2one("sf.member", string="Promoted Out By")
    promotion_date = fields.Date("Promotion Date")
    promotion_effective_date = fields.Date("Promotion Effective Date")

    promotion_reason = fields.Selection(
        [("promoted", "Fulfilled Promotion Criteria"), ("other", "Other")],
        string="Promotion Reason",
    )

    # action to promote consultant to manager
    def promote_prospective_manager(self):
        # promotion_date = fields.Datetime.now()
        # promotion_effective_date = promotion_date.replace(day=1) + relativedelta(months=+1)

        for prospective_manager in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            current_manager_id = prospective_manager.manager_id.id
            current_distributor_id = prospective_manager.related_distributor_id
            prospective_manager_vals = {
                "genealogy": "manager",
                "previous_genealogy": "prospective_manager",
                "promotion_date": self.promotion_date,
                "promotion_effective_date": self.promotion_effective_date,
                "promoter_id": self.promoter_id.id,
                "manager_id": prospective_manager.id,
                "previous_manager_id": current_manager_id,
                "move_date": self.promotion_date,
                "related_prospective_manager_id": False,
                "parent_id": current_distributor_id.id,
                "distribution_id": current_distributor_id.distribution_id.id,
            }

            prospective_manager.write(prospective_manager_vals)

            related_prospective_manager_id = prospective_manager.id

            recruited_by_consultants_ids = self.env["sf.member"].search(
                [
                    (
                        "related_prospective_manager_id",
                        "=",
                        related_prospective_manager_id,
                    ),
                    ("manager_id", "=", current_manager_id),
                ]
            )

            for recruited_by_consultant in self.env["sf.member"].browse(
                recruited_by_consultants_ids.ids
            ):
                recruited_by_consultant_vals = {
                    "manager_id": related_prospective_manager_id,
                    "previous_manager_id": current_manager_id,
                    "move_date": self.promotion_date,
                    "related_prospective_manager_id": False,
                    "parent_id": related_prospective_manager_id,
                    "distribution_id": current_distributor_id.distribution_id.id,
                }

                recruited_by_consultant.write(recruited_by_consultant_vals)

            recruited_by_leads_ids = self.env["sf.recruit"].search(
                [
                    (
                        "related_prospective_manager_id",
                        "=",
                        related_prospective_manager_id,
                    ),
                    ("manager_id", "=", current_manager_id),
                ]
            )

            for recruited_by_lead in self.env["sf.recruit"].browse(
                recruited_by_leads_ids.ids
            ):
                self.env.cr.execute(
                    """
                                   UPDATE sf_recruit
                                   SET manager_id=%s, previous_manager_id=%s, move_date=%s, related_prospective_manager_id=NULL
                                   WHERE id=%s
                                 """,
                    (
                        related_prospective_manager_id,
                        current_manager_id,
                        self.promotion_date,
                        recruited_by_lead.id,
                    ),
                )


class ManagerPromoteWizard(models.TransientModel):
    _name = "manager.promotion.wizard"
    _description = "Manager Promotion Wizard"

    promoter_id = fields.Many2one("sf.member", string="Promoted By")
    promotion_date = fields.Date("Promotion Date")
    promotion_effective_date = fields.Date("Promotion Effective Date")

    promotion_reason = fields.Selection(
        [("promoted", "Fulfilled Promotion Criteria"), ("other", "Other")],
        string="Promotion Reason",
    )

    # action to promote manager to distributor
    def promote_manager(self):
        # promotion_date = fields.Datetime.now()
        # promotion_effective_date = promotion_date.replace(day=1) + relativedelta(months=+1)

        for manager in self.env["sf.member"].browse(self._context.get("active_ids")):
            current_distributor_id = manager.related_distributor_id.id

            manager_vals = {
                "genealogy": "prospective_distributor",
                "previous_genealogy": "manager",
                "promotion_date": self.promotion_date,
                "promotion_effective_date": self.promotion_effective_date,
                "promoter_id": self.promoter_id.id,
                "related_prospective_distributor_id": manager.id,
            }

            manager.write(manager_vals)

            related_prospective_distributor_id = manager.id

            promoted_by_manager_ids = self.env["sf.member"].search(
                [
                    ("genealogy", "=", "manager"),
                    ("promoter_id", "=", related_prospective_distributor_id),
                    ("related_distributor_id", "=", current_distributor_id),
                ]
            )

            for manager in self.env["sf.member"].browse(promoted_by_manager_ids.ids):
                manager_vals = {
                    "related_prospective_distributor_id": related_prospective_distributor_id,
                }

                manager.write(manager_vals)


class ProspectiveDistributorPromoteWizard(models.TransientModel):
    _name = "prospective_distributor.promotion.wizard"
    _description = "Prospective Distributor Promotion Wizard"

    promoter_id = fields.Many2one("sf.member", string="Promoted Out By")
    promotion_date = fields.Date("Promotion Date")
    promotion_effective_date = fields.Date("Promotion Effective Date")
    distribution_id = fields.Many2one(
        "sf.distribution", string="New Distribution Name", required=True
    )

    promotion_reason = fields.Selection(
        [("promoted", "Fulfilled Promotion Criteria"), ("other", "Other")],
        string="Promotion Reason",
    )

    # action to promote manager to distributor
    def promote_prospective_distributor(self):
        if not self.distribution_id:
            raise UserError("Please Select Distribution To Promote")

        # promotion_date = fields.Datetime.now()
        # promotion_effective_date = promotion_date.replace(day=1) + relativedelta(months=+1)

        for prospective_distributor in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            current_distributor_id = prospective_distributor.related_distributor_id
            prospective_distributor_vals = {
                "genealogy": "distributor",
                "previous_genealogy": "prospective_distributor",
                "promotion_date": self.promotion_date,
                "promotion_effective_date": self.promotion_effective_date,
                "promoter_id": self.promoter_id.id,
                "related_distributor_id": prospective_distributor.id,
                "previous_distributor_id": current_distributor_id,
                "move_date": self.promotion_date,
                "related_prospective_distributor_id": False,
                "parent_id": False,
                "distribution_id": self.distribution_id.id,
            }

            prospective_distributor.write(prospective_distributor_vals)

            related_prospective_distributor_id = prospective_distributor.id

            prospective_distributor_manager_ids = self.env["sf.member"].search(
                [
                    (
                        "related_prospective_distributor_id",
                        "=",
                        related_prospective_distributor_id,
                    ),
                    ("related_distributor_id", "=", current_distributor_id.id),
                ]
            )
            for manager in self.env["sf.member"].browse(
                prospective_distributor_manager_ids.ids
            ):
                manager_vals = {
                    "related_distributor_id": related_prospective_distributor_id,
                    "previous_distributor_id": current_distributor_id,
                    "move_date": self.promotion_date,
                    "related_prospective_distributor_id": False,
                    "parent_id": related_prospective_distributor_id,
                    "distribution_id": prospective_distributor.distribution_id.id,
                }

                manager.write(manager_vals)


class DistributorDemoteWizard(models.TransientModel):
    _name = "distributor.demotion.wizard"
    _description = "Distributor Demotion Wizard"

    default_move_distributor_id = fields.Many2one(
        "sf.member", string="Move Managers To Distributor"
    )
    demotion_date = fields.Date("Demotion Date")
    demotion_effective_date = fields.Date("Demotion Effective Date")

    demotion_reason = fields.Selection(
        [("promoted", "Non-Payment"), ("other", "Other")], string="Demotion Reason"
    )

    # Action to demote distributor to manager
    def demote_distributor(self):
        # demotion_date = fields.Datetime.now()
        # demotion_effective_date = demotion_date.replace(day=1) + relativedelta(months=+1)

        for distributor in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            current_distributor_id = distributor.id

            distributor_manager_ids = self.env["sf.member"].search(
                [
                    ("genealogy", "=", "manager"),
                    ("related_distributor_id", "=", current_distributor_id),
                ]
            )

            for manager in self.env["sf.member"].browse(distributor_manager_ids.ids):
                # Move all linked managers to selected default distribution
                manager_vals = {
                    "related_distributor_id": self.default_move_distributor_id.id,
                    "previous_distributor_id": current_distributor_id,
                    "move_date": self.demotion_date,
                    "related_prospective_distributor_id": False,
                    "parent_id": self.default_move_distributor_id.id,
                    "distribution_id": self.default_move_distributor_id.distribution_id.id,
                }
                manager.write(manager_vals)

            distributor_vals = {
                "genealogy": "manager",
                "previous_genealogy": "distributor",
                "demotion_date": self.demotion_date,
                "demotion_effective_date": self.demotion_effective_date,
                "related_distributor_id": self.default_move_distributor_id.id,
                "previous_distributor_id": current_distributor_id,
                "move_date": self.demotion_date,
                "parent_id": self.default_move_distributor_id.id,
                "distribution_id": self.default_move_distributor_id.distribution_id.id,
            }
            distributor.write(distributor_vals)


class MangerDemoteWizard(models.TransientModel):
    _name = "manager.demotion.wizard"
    _description = "Manger Demotion Wizard"

    default_move_manager_id = fields.Many2one(
        "sf.member", string="Move Consultants To Manager"
    )
    demotion_date = fields.Date("Demotion Date")
    demotion_effective_date = fields.Date("Demotion Effective Date")

    demotion_reason = fields.Selection(
        [("promoted", "Non-Payment"), ("other", "Other")], string="Demotion Reason"
    )

    # action to promote manager to distributor
    def demote_manager(self):
        # demotion_date = fields.Datetime.now()
        # demotion_effective_date = demotion_date.replace(day=1) + relativedelta(months=+1)

        for manager in self.env["sf.member"].browse(self._context.get("active_ids")):
            current_manager_id = manager.id

            manager_consultant_ids = self.env["sf.member"].search(
                [
                    ("genealogy", "=", "consultant"),
                    ("manager_id", "=", current_manager_id),
                ]
            )

            for consultant in self.env["sf.member"].browse(
                manager_consultant_ids.ids
            ):
                # Move all linked consultants to selected default manager
                consultant_vals = {
                    "manager_id": self.default_move_manager_id.id,
                    "previous_manager_id": current_manager_id,
                    "move_date": self.demotion_date,
                    "parent_id": self.default_move_manager_id.id,
                    "distribution_id": self.default_move_manager_id.distribution_id.id,
                }

                consultant.write(consultant_vals)

            manager_lead_ids = self.env["sf.recruit"].search(
                [("manager_id", "=", current_manager_id)]
            )

            for lead in self.env["sf.recruit"].browse(manager_lead_ids.ids):
                # Move all linked leads/recruits to selected default manager
                lead_vals = {
                    "manager_id": self.default_move_manager_id.id,
                    "previous_manager_id": current_manager_id,
                    "move_date": self.demotion_date,
                }

                lead.write(lead_vals)

            manager_vals = {
                "genealogy": "consultant",
                "previous_genealogy": "prospective_manager",
                "demotion_date": self.demotion_date,
                "demotion_effective_date": self.demotion_effective_date,
                "manager_id": self.default_move_manager_id.id,
                "previous_manager_id": current_manager_id,
                "move_date": self.demotion_date,
                "parent_id": self.default_move_manager_id.id,
                "distribution_id": self.default_move_manager_id.distribution_id.id,
            }

            manager.write(manager_vals)
