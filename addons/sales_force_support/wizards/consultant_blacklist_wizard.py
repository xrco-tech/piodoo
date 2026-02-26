# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/wizards/consultant_blacklist_wizard.py

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging


_logger = logging.getLogger(__name__)


class ConsultantSuspendWizard(models.TransientModel):
    _name = "consultant.suspend.wizard"
    _description = "Consultant Suspend Wizard"

    suspend_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Suspend Reason"
    )

    def suspend_consultant(self):
        suspended_date = fields.Datetime.now()

        for consultant in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            consultant_vals = {
                "active_status": "suspended",
                "suspended_date": suspended_date,
            }

            consultant.write(consultant_vals)


class ManagerSuspendWizard(models.TransientModel):
    _name = "manager.suspend.wizard"
    _description = "Manager Suspend Wizard"

    suspend_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Suspend Reason"
    )

    def suspend_manager(self):
        suspended_date = fields.Datetime.now()

        for manager in self.env["sf.member"].browse(self._context.get("active_ids")):
            manager_vals = {
                "active_status": "suspended",
                "suspended_date": suspended_date,
            }

            manager.write(manager_vals)


class DistributorSuspendWizard(models.TransientModel):
    _name = "distributor.suspend.wizard"
    _description = "Manager Suspend Wizard"

    suspend_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Suspend Reason"
    )

    def suspend_distributor(self):
        suspended_date = fields.Datetime.now()

        for distributor in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            distributor_vals = {
                "active_status": "suspended",
                "suspended_date": suspended_date,
            }

            distributor.write(distributor_vals)


class ConsultantBlacklistWizard(models.TransientModel):
    _name = "consultant.blacklist.wizard"
    _description = "Consultant Blacklist Wizard"

    blacklist_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Blacklist Reason"
    )

    def blacklist_consultant(self):
        blacklisted_date = fields.Datetime.now()

        for consultant in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            consultant_vals = {
                "active_status": "blacklisted",
                "blacklisted_date": blacklisted_date,
            }

            consultant.write(consultant_vals)


class ManagerBlacklistWizard(models.TransientModel):
    _name = "manager.blacklist.wizard"
    _description = "Manager Blacklist Wizard"

    blacklist_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Blacklist Reason"
    )

    def blacklist_manager(self):
        blacklisted_date = fields.Datetime.now()

        for manager in self.env["sf.member"].browse(self._context.get("active_ids")):
            manager_vals = {
                "active_status": "blacklisted",
                "blacklisted_date": blacklisted_date,
            }

            manager.write(manager_vals)


class DistributorBlacklistWizard(models.TransientModel):
    _name = "distributor.blacklist.wizard"
    _description = "Distributor Blacklist Wizard"

    blacklist_reason = fields.Selection(
        [("non_payment", "Non-Payment"), ("other", "Other")], string="Blacklist Reason"
    )

    def blacklist_distributor(self):
        blacklisted_date = fields.Datetime.now()

        for distributor in self.env["sf.member"].browse(
            self._context.get("active_ids")
        ):
            distributor_vals = {
                "active_status": "blacklisted",
                "blacklisted_date": blacklisted_date,
            }

            distributor.write(distributor_vals)
