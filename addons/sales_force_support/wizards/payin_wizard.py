# Source: bb_payin/wizards/payin_wizard.py
import time
import json
import io

from dateutil.relativedelta import relativedelta

from odoo import api, models, fields, _
from odoo.exceptions import UserError
from operator import itemgetter
from odoo.http import request
from odoo.tools import date_utils
import logging

_logger = logging.getLogger(__name__)

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class BbPayinSheetChangeStateWizard(models.TransientModel):
    _name = "bb.payin.change.state"
    _description = "Payin Sheet Change State Wizard"

    def default_get(self, fields):
        result = super(BbPayinSheetChangeStateWizard, self).default_get(fields)
        result["payin_ids"] = self.env["bb.payin.sheet"].browse(
            self._context.get("active_ids")
        )
        return result

    payin_ids = fields.Many2many("bb.payin.sheet")

    def change_state(self):
        for payin in self.env["bb.payin.sheet"].browse(self._context.get("active_ids")):
            # check if the no. of pages is zero and set is_no_sale to True
            if payin.no_of_pages == 0:
                payin.is_no_sales = True
                payin.state = "verified"
                payin.registered_date = fields.Date.today()
                if not payin.received_date:
                    payin.received_date = fields.Date.today()

            if not payin.registered_date:
                payin.state = "registered"
                payin.registered_date = fields.Date.today()
                if not payin.received_date:
                    payin.received_date = fields.Date.today()


class BbPayinSheetWizard(models.TransientModel):
    _name = "bb.payin.sheet.wizard"
    _description = "Payin Sheet Wizard"

    all = fields.Boolean("All Distributors")
    distributor_ids = fields.Many2many(
        "sf.member",
        string="Distributors",
    )
    distribution_ids = fields.Many2many("res.partner", string="Distribution")
    date = fields.Date("Month/Year", default=time.strftime("%Y-%m-%d"))
    date_sale = fields.Integer("Consultant Active Months", default=3)
    date_new_consultant = fields.Integer(
        "Prospective Consultant Active Months", default=3
    )
    payin_date = fields.Date("Capture Date")

    per_manager = fields.Boolean(string="Per Manager?", default=False)
    manager_id = fields.Many2one("sf.member", string="Manager")

    def _sort_distributor_recordset(self, distributors):
        sorted_distributor_ids = sorted(
            distributors.ids,
            key=lambda id: distributors.browse(id).partner_id.known_name,
        )

        return sorted_distributor_ids

    def create_payin(self):
        sheets = self.env["bb.payin.sheet"]

        date = self.payin_date.replace(day=1)
        date_new_consultant = date.today() - relativedelta(day=1)
        date_new_consultant = date_new_consultant - relativedelta(
            months=+self.date_new_consultant
        )

        distributors = self.env["sf.member"].search(
            [
                ("id", "in", self.distributor_ids.ids),
                ("genealogy", "=", "distributor"),
            ]
        )
        sorted_distributor_ids = self._sort_distributor_recordset(distributors)
        sorted_distributors = self.env["sf.member"].browse(sorted_distributor_ids)
        if self.all:
            distributors = self.env["sf.member"].search(
                [
                    ("genealogy", "=", "distributor"),
                    # ('active_status', 'in', ['active1', 'active2', 'active3', 'active4', 'active5', 'active6'])
                ]
            )

            sorted_distributor_ids = self._sort_distributor_recordset(distributors)
            sorted_distributors = self.env["sf.member"].browse(sorted_distributor_ids)

        for distributor in sorted_distributors:
            distributor_vals = {
                "distributor_id": distributor.id,
                "date": date,
                "payin_date": date,
                "distribution_company_id": distributor.partner_id.id,
                "distributor_known_name": distributor.partner_id.known_name,
            }

            if not self.per_manager:
                managers = distributor + self.env["sf.member"].search(
                    [
                        ("related_distributor_id", "=", distributor.id),
                        ("genealogy", "in", ["manager", "prospective_distributor"]),
                        # ('active_status', 'in', ['active1', 'active2', 'active3', 'active4', 'active5', 'active6'])
                    ]
                )
            if self.per_manager:
                if len(distributors) > 1:
                    raise UserError(
                        _(
                            "You need to pick 1 distributor and 1 manager to create a Pay-In Sheet Pack per Manager."
                        )
                    )

                managers = self.manager_id

            # Sorting managers to create in payin sheets
            managers = sorted(managers, key=itemgetter("name"), reverse=False)

            distributor_payin_lines = [
                {
                    "manager_id": distributor.id,
                    "manager_name": distributor.partner_id.known_name,
                }
            ]

            for manager in managers:
                if manager.id != distributor.id:
                    distributor_payin_lines.append(
                        ({"manager_id": manager.id, "manager_name": manager.known_name})
                    )
                    print(distributor_payin_lines)

                # add distributor company to creation of manager Pay-In
                vals = {
                    "manager_id": manager.id,
                    "distributor_id": distributor.id,
                    "distribution_company_id": distributor.partner_id.id,
                    "date": date,
                    "state": "new",
                    "payin_date": date,
                    "distributor_known_name": distributor.partner_id.known_name,
                    "manager_known_name": manager.partner_id.known_name,
                }

                manager_payin_lines = [
                    {"consultant_id": manager.id, "consultant_name": manager.name}
                ]

                consultants = self.env["sf.member"].search_read(
                    [
                        ("manager_id", "=", manager.id),
                        ("genealogy", "in", ["consultant", "prospective_manager"]),
                        (
                            "active_status",
                            "in",
                            [
                                "pay_in_sheet_pending",
                                "active1",
                                "active2",
                                "active3",
                                "active4",
                                "active5",
                                "active6",
                            ],
                        ),
                    ],
                    fields=["id", "name"],
                )

                potential_consultants = self.env["sf.member"].search_read(
                    [
                        ("manager_id", "=", manager.id),
                        ("genealogy", "=", "potential_consultant"),
                    ],
                    fields=["id", "name"],
                )

                for consultant in consultants:
                    manager_payin_lines.append(
                        {
                            "consultant_id": consultant["id"],
                            "consultant_name": consultant["name"],
                        }
                    )

                for potential_consultant in potential_consultants:
                    manager_payin_lines.append(
                        {
                            "consultant_id": potential_consultant["id"],
                            "consultant_name": potential_consultant["name"],
                        }
                    )

                manager_payin_lines = sorted(
                    manager_payin_lines,
                    key=itemgetter("consultant_name"),
                    reverse=False,
                )
                manager_payin_lines = [
                    (0, 0, {"consultant_id": x["consultant_id"]})
                    for x in manager_payin_lines
                ]

                vals["payin_line_ids"] = manager_payin_lines

                payin_pack = self.env["bb.payin.sheet"].search(
                    [
                        ("date", "=", date),
                        ("distribution_company_id", "=", distributor.partner_id.id),
                        ("manager_id", "=", manager.id),
                    ]
                )
                if not payin_pack:
                    payin_sheet = self.env["bb.payin.sheet"].create(vals)
                    sheets |= payin_sheet
                else:
                    raise UserError(
                        _(
                            f"You cannot create {distributor.distribution_id.name} Pay-In Sheets Pack for {payin_pack.period} as it already exist."
                        )
                    )

            distributor_payin_lines = sorted(
                distributor_payin_lines, key=itemgetter("manager_name"), reverse=False
            )
            distributor_payin_lines = [
                (0, 0, {"manager_id": x["manager_id"]}) for x in distributor_payin_lines
            ]

            distributor_vals["payin_line_ids"] = distributor_payin_lines

            dist_summary = self.env["payin.distributor"].search(
                [("date", "=", date), ("distributor_id", "=", distributor.id)]
            )

            if not dist_summary:
                self.env["payin.distributor"].create(distributor_vals)

            if self.per_manager:
                if not self.env["payin.distributor"].search_count(
                    [
                        ("payin_line_ids.manager_id", "=", manager.id),
                        ("date", "=", date),
                        ("id", "=", dist_summary.id),
                    ]
                ):
                    dist_summary.write(
                        {"payin_line_ids": [(0, 0, {"manager_id": manager.id})]}
                    )

        tree_view_id = self.env.ref("sales_force_support.payin_tree_view").id
        form_view_id = self.env.ref("sales_force_support.payin_form_view").id
        domain = [("id", "in", sheets.ids)]

        action = {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "list"), (form_view_id, "form")],
            "view_mode": "tree,form",
            "name": _("Created Pay-In Sheets"),
            "res_model": "bb.payin.sheet",
            "domain": domain,
            "target": "main",
        }
        return action


class BbPayinDistributorSheetChangeStateWizard(models.TransientModel):
    _name = "bb.payin.distributor.change.state"
    _description = "Distributor Summary Change State Wizard"

    def change_state(self):
        for payin in self.env["payin.distributor"].browse(
            self._context.get("active_ids")
        ):

            if payin.no_of_pages == 0:
                payin.is_no_sales = True
                payin.state = "verified"
                payin.registered_date = fields.Date.today()
                if not payin.received_date:
                    payin.received_date = fields.Date.today()

            if not payin.registered_date:
                payin.state = "registered"
                payin.registered_date = fields.Date.today()
                if not payin.received_date:
                    payin.received_date = fields.Date.today()


class BbPayinDistributorWizard(models.TransientModel):
    _name = "bb.payin.distributor.wizard"
    _description = "Payin Distributor Wizard"

    all = fields.Boolean("All Distributors")
    distributor_ids = fields.Many2many("sf.member", string="Distributors")
    distribution_ids = fields.Many2many("res.partner", string="Distribution")
    date = fields.Date("Month/Year", default=time.strftime("%Y-%m-%d"))
    date_sale = fields.Integer("Consultant Active Months", default=1)
    date_new_consultant = fields.Integer(
        "Prospective Consultant Active Months", default=1
    )
    payin_date = fields.Date("Captured Period")

    def create_payin(self):
        sheets = self.env["payin.distributor"]
        date = self.payin_date.replace(day=1)
        date_sale = date.today() - relativedelta(day=1)
        date_new_consultant = date.today() - relativedelta(day=1)
        date_sale = date_sale - relativedelta(months=+self.date_sale)
        date_new_consultant = date_new_consultant - relativedelta(
            months=+self.date_new_consultant
        )

        distributors = self.env["sf.member"].search(
            [
                ("distribution_id", "in", self.distribution_ids.ids),
                ("genealogy", "=", "distributor"),
            ]
        )
        if self.all:
            distributors = self.env["sf.member"].search(
                [
                    ("genealogy", "=", "distributor"),
                ]
            )

        for distributor in distributors:
            vals = {
                "distributor_id": distributor.id,
                "date": date,
                "payin_date": date,
                "state": "new",
                "distribution_company_id": distributor.partner_id.id,
                "payin_line_ids": [(0, 0, {"manager_id": distributor.id})],
            }

            managers = self.env["sf.member"].search(
                [
                    ("distributor_id", "=", distributor.id),
                    ("genealogy", "=", "manager"),
                ]
            )

            for manager in managers:
                ids = []
                if manager.id not in ids:
                    line_vals = {"manager_id": manager.id}
                    vals["payin_line_ids"].append((0, 0, line_vals))
                    ids.append(manager.id)

            payin_sheet = self.env["payin.distributor"].create(vals)
            sheets |= payin_sheet

        tree_view_id = self.env.ref("sales_force_support.payin_distributor_tree_view").id
        form_view_id = self.env.ref("sales_force_support.payin_distributor_form_view").id
        domain = [("id", "in", sheets.ids)]

        action = {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "list"), (form_view_id, "form")],
            "view_mode": "tree,form",
            "name": _("Pay-In Sheet Distributor Summary"),
            "res_model": "payin.distributor",
            "domain": domain,
            "target": "main",
        }
        return action


class BbPayinSheetExportNewPayinsFormsExcelWizard(models.TransientModel):
    _name = "bb.payin.export.payins.new"
    _description = "Payin Sheet Export New Pay-Ins Form Wizard"

    def print_new_payins_form_xls(self):
        _logger.info("This is  print Excel %s", self._context)
        active_records = self._context["active_ids"]
        records = self.env["bb.payin.sheet"].browse(active_records)
        _logger.info("This is  print Excel Records %s", records)
        data = {
            "model": self._name,
            "ids": self.ids,
            "records": records.ids,
        }
        report_name = "Excel Pay-In Sheets Form"
        return {
            "type": "ir.actions.report",
            "data": {
                "model": "bb.payin.export.payins.new",
                "options": json.dumps(data, default=date_utils.json_default),
                "output_format": "xlsx",
                "report_name": report_name,
            },
            "report_type": "xlsx",
        }

    def get_xlsx_report(self, data, response):
        _logger.info("This is  get_xlsx_report %s", data)
        _logger.info("this is get_xlsx_report response %s", response)
        active_ids = data["records"]
        _logger.info("active_ids %s", active_ids)

        active_records = self.env["bb.payin.sheet"].browse(active_ids)
        _logger.info("actibve recorddsss %s", active_records)

        unique_distributors = self.env["bb.payin.sheet"].read_group(
            [("id", "in", active_ids)],
            fields=["distributor_id", "period"],
            groupby=["distributor_id", "period"],
            lazy=False,
        )

        _logger.info("unique_distributors %s", unique_distributors)

        unique_distributors_and_dates = [
            {"distributor_id": x["distributor_id"][0], "period": x["period"]}
            for x in unique_distributors
        ]
        _logger.info("unique_distributors_and_dates %s", unique_distributors_and_dates)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(
            output, {"in_memory": True, "strings_to_numbers": False}
        )

        # Set the formats:
        format1 = workbook.add_format(
            {"font_size": 14, "bold": True, "bg_color": "#CCCCFF"}
        )
        format1.set_border(1)
        format1.set_border_color("#000000")

        format2 = workbook.add_format({"font_size": 14})
        format2.set_border(1)
        format2.set_border_color("#000000")

        format2_unlocked = workbook.add_format({"font_size": 14, "locked": False})
        format2_unlocked.set_border(1)
        format2_unlocked.set_border_color("#000000")

        format3 = workbook.add_format({"font_size": 11, "bold": True})
        format3.set_border(1)
        format3.set_border_color("#000000")

        format4 = workbook.add_format({"font_size": 11})
        format4.set_border(1)
        format4.set_border_color("#000000")

        format4_unlocked = workbook.add_format({"font_size": 11, "locked": False})
        format4_unlocked.set_border(1)
        format4_unlocked.set_border_color("#000000")

        format5 = workbook.add_format({"font_size": 11, "bg_color": "#F2F2F2"})
        format5.set_border(1)
        format5.set_border_color("#000000")

        format6 = workbook.add_format({"font_size": 11, "bg_color": "#D9D9D9"})
        format6.set_border(1)
        format6.set_border_color("#000000")

        for record in unique_distributors_and_dates[:1]:
            distributor_summary = self.env["payin.distributor"].search(
                [
                    ("distributor_id", "=", record["distributor_id"]),
                    ("period", "=", record["period"]),
                ],
                limit=1,
            )

            distributor_sheet = workbook.add_worksheet(
                f"Summary - {distributor_summary.distribution_known_name}"
            )
            # Protect the worksheet.
            distributor_sheet.protect()

            # Set the column widths:
            distributor_sheet.set_column("A:A", 10)
            distributor_sheet.set_column("B:B", 35)
            distributor_sheet.set_column("C:C", 10)
            distributor_sheet.set_column("D:D", 35)
            distributor_sheet.set_column("E:E", 20)
            distributor_sheet.set_column("F:F", 20)

            distributor_sheet.write("A1", "DCode", format1)
            distributor_sheet.write("B1", "Distribution", format1)
            distributor_sheet.write("C1", "MCode", format1)
            distributor_sheet.write("D1", "MName", format1)
            distributor_sheet.write("E1", "Actual Sales", format1)
            distributor_sheet.write("F1", "Comments", format1)

            row_index = 2

            for dist_line in distributor_summary.payin_line_ids:
                distributor_sheet.write(
                    f"A{row_index}",
                    int(distributor_summary.distributor_sales_force_code),
                    format2,
                )
                distributor_sheet.write(
                    f"B{row_index}",
                    f"{distributor_summary.distribution_known_name}",
                    format2,
                )
                distributor_sheet.write(
                    f"C{row_index}", int(dist_line.sales_force_code), format2
                )
                distributor_sheet.write(
                    f"D{row_index}", f"{dist_line.manager_id.name}", format2
                )
                distributor_sheet.write(f"E{row_index}", "", format2_unlocked)
                distributor_sheet.write(f"F{row_index}", "", format2_unlocked)
                row_index += 1

            distributor_sheet.write(f"D{row_index + 1}", "TOTAL", format2)
            distributor_sheet.write(
                f"E{row_index + 1}", f"=SUM(E$2:E{row_index - 1})", format2
            )

            manager_payins = self.env["bb.payin.sheet"].search(
                [
                    ("distributor_id", "=", record["distributor_id"]),
                    ("period", "=", record["period"]),
                ]
            )

            for payin_rec in manager_payins:
                manager_sheet = workbook.add_worksheet(
                    f"{payin_rec.manager_id.name} - {distributor_summary.distribution_known_name}"
                )
                # Protect the worksheet.
                manager_sheet.protect()

                # Set the column widths:
                manager_sheet.set_column("A:A", 7)
                manager_sheet.set_column("B:B", 30)
                manager_sheet.set_column("C:C", 7)
                manager_sheet.set_column("D:D", 15)
                manager_sheet.set_column("E:E", 7)
                manager_sheet.set_column("F:F", 30)
                manager_sheet.set_column("G:G", 12)
                manager_sheet.set_column("H:H", 15)
                manager_sheet.set_column("I:I", 12)
                manager_sheet.set_column("J:J", 12)
                manager_sheet.set_column("K:K", 12)
                manager_sheet.set_column("L:L", 12)
                manager_sheet.set_column("M:M", 12)
                manager_sheet.set_column("N:N", 12)
                manager_sheet.set_column("O:O", 12)
                manager_sheet.set_column("P:P", 12)

                manager_sheet.write("A1", "DCode", format3)
                manager_sheet.write("B1", "Distribution", format3)
                manager_sheet.write("C1", "MCode", format3)
                manager_sheet.write("D1", "MName", format3)
                manager_sheet.write("E1", "CCode", format3)
                manager_sheet.write("F1", "Consultant", format3)
                manager_sheet.write("G1", "Number1", format3)
                manager_sheet.write("H1", "RSA ID", format3)
                manager_sheet.write("I1", "BBH Sales", format3)
                manager_sheet.write("J1", "BBH Returns", format3)
                manager_sheet.write("K1", "BBH Total", format3)
                manager_sheet.write("L1", "Puer Sales", format3)
                manager_sheet.write("M1", "Puer Returns", format3)
                manager_sheet.write("N1", "Puer Total", format3)
                manager_sheet.write("O1", "Grand Total", format3)
                manager_sheet.write("P1", "Comments", format3)

                man_row_index = 2

                for man_line in payin_rec.payin_line_ids:
                    manager_sheet.write(
                        f"A{man_row_index}",
                        int(distributor_summary.distributor_sales_force_code),
                        format4,
                    )
                    manager_sheet.write(
                        f"B{man_row_index}",
                        f"{distributor_summary.distribution_known_name}",
                        format4,
                    )

                    manager_sheet.write(
                        f"C{man_row_index}",
                        int(payin_rec.manager_sales_force_code),
                        format4,
                    )
                    manager_sheet.write(
                        f"D{man_row_index}", f"{payin_rec.manager_id.name}", format4
                    )

                    manager_sheet.write(
                        f"E{man_row_index}", int(man_line.sales_force_code), format4
                    )
                    manager_sheet.write(
                        f"F{man_row_index}", f"{man_line.consultant_id.name}", format4
                    )

                    if man_line.consultant_id.mobile:
                        manager_sheet.write(
                            f"G{man_row_index}",
                            f"{man_line.consultant_id.mobile}",
                            format4,
                        )
                    else:
                        manager_sheet.write(f"G{man_row_index}", "", format4)

                    if man_line.consultant_id.sa_id:
                        manager_sheet.write(
                            f"H{man_row_index}",
                            f"{man_line.consultant_id.sa_id}",
                            format4,
                        )
                    elif man_line.consultant_id.passport:
                        manager_sheet.write(
                            f"H{man_row_index}",
                            f"{man_line.consultant_id.passport}",
                            format4,
                        )
                    else:
                        manager_sheet.write(f"H{man_row_index}", "", format4)

                    manager_sheet.write(f"I{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"J{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(
                        f"K{man_row_index}",
                        f"=+I{man_row_index}-J{man_row_index}",
                        format4,
                    )
                    manager_sheet.write(f"L{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"M{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(
                        f"N{man_row_index}",
                        f"=+L{man_row_index}-M{man_row_index}",
                        format4,
                    )
                    manager_sheet.write(
                        f"O{man_row_index}",
                        f"=+K{man_row_index}+N{man_row_index}",
                        format4,
                    )
                    manager_sheet.write(f"P{man_row_index}", "", format4_unlocked)
                    man_row_index += 1

                for extra_line in range(0, 15):
                    manager_sheet.write(f"A{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"B{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"C{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"D{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"E{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"F{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"G{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"H{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"I{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"J{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"K{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"L{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"M{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"N{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"O{man_row_index}", "", format4_unlocked)
                    manager_sheet.write(f"P{man_row_index}", "", format4_unlocked)
                    man_row_index += 1

        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()

        return {"type": "ir.actions.act_window_close"}


class BBPayinActiveStatusConfigWizard(models.TransientModel):
    _name = "bb.payin.active.status.wizard"
    _description = "Active Status Config Wizard"

    reference_payin_date = fields.Date(
        "Reference Pay-In Sheets Date", default=time.strftime("%Y-%m-%d")
    )
    next_schedule_run_date = fields.Datetime(
        "Next Schedule Run Date/Time", default=time.strftime("%Y-%m-%d")
    )

    def update_active_status_config(self):
        # Get the existing config settings record (or create a new one if it doesn't exist)
        config_settings = self.env["res.config.settings"].sudo().create({})

        # Update the configuration value
        config_settings.payin_active_status_reference_date = (
            self.reference_payin_date.replace(day=1)
        )

        # Save the changes
        config_settings.execute()

        # Find the cron job by name
        cron_job_name = "Update Sales Force Active Status"
        cron_job = (
            self.env["ir.cron"]
            .sudo()
            .search(
                [("name", "=", cron_job_name), ("active", "=", True)],
                order="write_date desc",
                limit=1,
            )
        )

        if cron_job:
            # Update the next execution time
            cron_job.write({"nextcall": self.next_schedule_run_date})
            return True
        else:
            return False
