# Source: bb_payin/wizards/payin_report_wizard.py
# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging


_logger = logging.getLogger(__name__)


class BbPayinSheetReportDistributorWizardPrirrnt(models.TransientModel):
    _name = "bb.payin.sheet.report.distributor.wizard.print"


class BbPayinSheetReportDistributorWizardPrint(models.TransientModel):
    _name = "bb.payin.print"
    _description = "Payin Sheet Report Distributor Wizard Print"
    company_id = fields.Many2one(
        "res.company", string="Company", compute="_get_company"
    )
    sheets = fields.Many2many("bb.payin.sheet", string="Sheets")
    distributor_sumarry_id = fields.Many2one("payin.distributor", "Distributor Summary")
    date = fields.Date(string="Date", default=lambda s: fields.Date.context_today(s))

    def empty_rows(self):
        return [None for i in range(10)]

    def get_dist(self, o, doc):

        doc.distributor = o.id

        return ""

    def _get_company(self):
        for rec in self:
            rec.company_id = self.env.user.company_id.id

    def print_to_documents(self):
        ids = []
        self.sheets = self.env["bb.payin.sheet"].browse(self._context.get("active_ids"))
        distributors = self.sheets.mapped("distributor_id")
        dis_ids = []
        if self.sheets:
            for distributor in distributors:
                if distributor.id not in dis_ids:
                    summary_id = self.env["payin.distributor"].search(
                        [
                            ("payin_date", "=", self.sheets[0].payin_date),
                            ("distributor_id", "=", distributor.id),
                        ],
                        limit=1,
                    )
                    if summary_id:
                        sheets = self.env["bb.payin.sheet"].search(
                            [
                                ("id", "in", self.sheets.ids),
                                ("distributor_id", "=", distributor.id),
                            ]
                        )
                        values = {"distributor_sumarry_id": summary_id.id}
                        wizard_id = self.env["bb.payin.print"].create(values)
                        wizard_id.sheets = sheets
                        for sheet in sheets:
                            sheet.distributor = 0
                        ids.append(wizard_id.id)
                    dis_ids.append(distributor.id)

        wizards = self.browse(ids)
        if not wizards:
            raise UserError(_("No destribution summary found."))

        template = self.env.ref("sales_force_support.payi_attachment")
        template_obj = self.env["mail.template"]
        mail_mail_obj = self.env["mail.mail"]
        attachment_obj = self.env["ir.attachment"]

        for wizard in wizards:
            values = template.generate_email(
                wizard.id,
                [
                    "subject",
                    "body_html",
                    "email_from",
                    "email_to",
                    "partner_to",
                    "email_cc",
                    "reply_to",
                    "scheduled_date",
                ],
            )
            atta_id = ""
            for attachment in values.get("attachments", []):
                attachment_data = {
                    "name": wizard.distributor_sumarry_id.distribution_company_id.name
                    + " Pay-In Sheets",
                    # 'datas_fname': partner.name + " Customer Statement.pdf",
                    "datas": attachment[1],
                    "res_model": "res.partner",
                    "res_id": wizard.distributor_sumarry_id.distribution_company_id.id,
                }
                atta_id = attachment_obj.create(attachment_data).id

                document = self.env["documents.document"].create(
                    {
                        "folder_id": self.env.ref("sales_force_support.sales_force_folder").id,
                        "attachment_id": atta_id,
                        "type": "binary",
                        "partner_id": wizard_id.distributor_sumarry_id.distribution_company_id.id,
                        "res_model": "res.partner",
                        "res_id": wizard_id.distributor_sumarry_id.distribution_company_id.id,
                    }
                )

    def print(self):
        ids = []
        self.sheets = self.env["bb.payin.sheet"].browse(self._context.get("active_ids"))
        distributors = self.sheets.mapped("distributor_id")
        dis_ids = []
        if self.sheets:
            for distributor in distributors:
                if distributor.id not in dis_ids:
                    summary_id = self.env["payin.distributor"].search(
                        [
                            ("payin_date", "=", self.sheets[0].payin_date),
                            ("distributor_id", "=", distributor.id),
                        ],
                        limit=1,
                    )
                    if summary_id:
                        sheets = self.env["bb.payin.sheet"].search(
                            [
                                ("id", "in", self.sheets.ids),
                                ("distributor_id", "=", distributor.id),
                            ]
                        )
                        values = {"distributor_sumarry_id": summary_id.id}
                        wizard_id = self.env["bb.payin.print"].create(values)
                        wizard_id.sheets = sheets
                        for sheet in sheets:
                            sheet.distributor = 0
                        ids.append(wizard_id.id)
                    dis_ids.append(distributor.id)

        wizards = self.browse(ids)
        if not wizards:
            raise UserError(_("No destribution summary found."))
        return self.env.ref("sales_force_support.action_report_payin_all").report_action(wizards)


class BbPayinSheetReportDistributorWizard(models.TransientModel):
    _name = "bb.payin.sheet.report.distributor.wizard"
    _description = "Payin Sheet Report Distributor Wizard"

    distributor_id = fields.Many2one("sf.member", string="Distributors")

    def print(self):
        sheets = self.env["bb.payin.sheet"].browse(self._context("active_ids"))
        return self.env.ref("sales_force_support.action_report_payin").report_action(sheets)

    def view(self):
        ids = (
            self.env["bb.payin.sheet"]
            .search(
                [("distributor_id", "=", self.distributor_id.id), ("state", "=", "new")]
            )
            .ids
        )
        tree_view_id = self.env.ref("sales_force_support.payin_tree_view").id
        form_view_id = self.env.ref("sales_force_support.payin_form_view").id
        domain = [("id", "=", ids)]

        action = {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "tree"), (form_view_id, "form")],
            "view_mode": "tree,form",
            "name": _("Pay-In Sheets"),
            "res_model": "bb.payin.sheet",
            "domain": domain,
            "target": "main",
        }
        return action
