# -*- coding: utf-8 -*-
# Source: bb_payin
from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
from math import ceil
import json
import math

_logger = logging.getLogger(__name__)


class BbPayinSheet(models.Model):
    _name = "bb.payin.sheet"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In Sheets"

    payin_line_ids = fields.One2many("bb.payin.sheet.line", "payin_sheet_id", "Lines")
    distributor_id = fields.Many2one("sf.member", "Distributor")
    distributor_known_name = fields.Char(string="Distributor Known Name")
    distributor_sales_force_code = fields.Char(
        related="distributor_id.sales_force_code", string="Distributor SFM Code"
    )
    distributor_mobile = fields.Char(
        related="distributor_id.mobile", string="Distributor mobile"
    )
    manager_mobile = fields.Char(related="manager_id.mobile", string="Manager mobile")
    distribution_known_name = fields.Char(
        related="distributor_id.known_name", string="Distribution Name", store=True
    )
    manager_id = fields.Many2one("sf.member", "Manager")
    manager_known_name = fields.Char(string="Manager Known Name")
    manager_sales_force_code = fields.Char(
        related="manager_id.sales_force_code", string="Manager SFM Code", store=True
    )
    date = fields.Date("Month/Year")
    capture_start_date = fields.Date("Capture Start Date", tracking=True)
    name = fields.Char("Name")
    state = fields.Selection(
        [
            ("new", "New"),
            ("registered", "Registered"),
            ("captured", "Captured"),
            ("verified", "Verified"),
        ],
        string="Status",
        default="new",
        tracking=3,
    )
    company_id = fields.Many2one(
        "res.company", string="Company", compute="_get_company"
    )
    user_id = fields.Many2one("res.users", string="Responsible", compute="_get_user")
    captured_by = fields.Char(string="Captured By", compute="_get_captured_by")
    sub_total = fields.Float("Grand Total", compute="_compute_totals")
    bb_brand_total = fields.Float("BB Total", compute="_compute_totals")
    brand_total = fields.Float("Brand Total", compute="_compute_totals")
    puer_brand_total = fields.Float("Puer Total", compute="_compute_totals")
    bb_sales = fields.Float("BB Sales", compute="_compute_totals")
    bb_returns = fields.Float("BB Returns", compute="_compute_totals")
    puer_sales = fields.Float("Puer Sales", compute="_compute_totals")
    puer_returns = fields.Float("Puer Returns", compute="_compute_totals")
    total_captured = fields.Float("Total Captured")
    registered = fields.Float("Registered")
    registered_date = fields.Date("Registered Date")
    received_date = fields.Date("Received Date", tracking=True)
    payin_date = fields.Date("Capture Date")
    wizard = fields.Boolean()
    timesheet_timer_start = fields.Datetime("Timesheet Timer Start", default=None)
    timesheet_timer_pause = fields.Datetime("Timesheet Timer Last Pause")
    timesheet_timer_first_start = fields.Datetime(
        "Timesheet Timer First Use", readonly=True
    )
    timesheet_timer_last_stop = fields.Datetime(
        "Timesheet Timer Last Use", readonly=True
    )
    consultants_captured = fields.Integer(
        "Number of Consultants Captured", compute="_compute_consultants_captured"
    )
    capture_time = fields.Float("Time to Capture")
    consultants_sales = fields.Integer(
        "Number of Consultants With Sales", compute="_compute_consultants_sales"
    )
    distributor = fields.Integer(string="Distributor ID")
    started = fields.Boolean()
    new_consultants_count = fields.Integer("New Consultants Captured")
    changed = fields.Boolean("Pay-In Changed")
    allow_edit = fields.Boolean("Allow Edit Pay-In", compute="_allow_edit")
    edit_registered_date = fields.Boolean(
        "Allow Edit registered_date", compute="_compute_edit_registered_date"
    )
    consultants_no_sales = fields.Integer(
        "Number of Consultants with No Sales", compute="_compute_consultants_sales"
    )
    number_of_owing_consultants = fields.Integer(
        string="Number of Consultants with Owing/Comments",
        compute="_compute_consultants_sales",
    )
    number_of_consultants_with_returns = fields.Integer(
        string="Number of Consultants with Returns",
        compute="_compute_consultants_sales",
    )
    distribution_company_id = fields.Many2one(
        "res.partner", string="Distribution", store=True
    )
    no_of_pages = fields.Integer("No. of Pages Registered", tracking=True)
    documents_count = fields.Integer(
        "Documents Count", compute="_compute_documents_count"
    )
    is_locked = fields.Boolean("Is locked?")
    lines_capture_start_date = fields.Datetime("Lines Timer")
    lines_capture_stop_date = fields.Datetime("Lines Stop Timer")
    period = fields.Char(string="Capture Period", compute="_compute_period", store=True)
    grouped_total_captured = fields.Float("Total")
    # New field to track received payin-sheet based on number of pages
    is_no_sales = fields.Boolean(string="No Sales", tracking=True, default=False)
    report_print_message = fields.Text(string="Report Print Message")
    total_captured = fields.Float(
        "Total Captured Summary Sales", compute="_compute_total_captured"
    )
    # New field to track existing consultants in a pay-in sheet
    payin_line_existing_consultant_ids = fields.Many2many(
        "sf.member",
        string="Payin Line Consultants",
        compute="_compute_payin_line_existing_consultant_ids",
    )

    @api.depends("payin_line_ids.consultant_id")
    def _compute_payin_line_existing_consultant_ids(self):
        for record in self:
            record.payin_line_existing_consultant_ids = record.payin_line_ids.mapped(
                "consultant_id"
            )

    def _compute_total_captured(self):
        payin = self.env["payin.distributor"].search(
            [("date", "=", self.date), ("distributor_id", "=", self.distributor_id.id)],
            limit=1,
        )
        self.total_captured = sum(
            [
                line.actual_sales
                for line in payin.payin_line_ids
                if line.manager_id.id == self.manager_id.id
            ]
        )

    @api.onchange("x_studio_status_update")
    def _onchange_x_studio_status_update(self):
        formatted_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.x_studio_latest_status_update = formatted_datetime

    @api.depends("payin_line_ids")
    def _exclude_zero_sales(self):
        filtered_records = []
        for rec in self.payin_line_ids:
            if (
                rec.bb_sales > 0
                or rec.bb_returns > 0
                or rec.puer_sales > 0
                or rec.puer_returns > 0
            ):
                filtered_records.append(rec)
        return filtered_records

    def _get_captured_by(self):
        self._cr.execute(
            """
            SELECT rp.name
            FROM mail_tracking_value mtv
            LEFT JOIN mail_message mm ON mm.id = mtv.mail_message_id
            LEFT JOIN res_partner rp ON rp.id = mm.author_id
            LEFT JOIN ir_model_fields f ON f.id = mtv.field_id
            WHERE f.name = 'state'
            AND mm.model = 'bb.payin.sheet'
            AND mtv.old_value_char = 'Registered'
            AND mm.res_id = %s
            ORDER BY mtv.id DESC
            LIMIT 1
        """,
            (self.id,),
        )
        captured_by_rec = self._cr.fetchone()
        self.captured_by = captured_by_rec[0] if captured_by_rec else ""

    @api.depends("date")
    def _compute_period(self):
        for rec in self:
            rec.period = " "

            if rec.date:
                rec.period = rec.get_date(rec.date)

    def action_lock(self):
        self.is_locked = True
        self.allow_edit = False

    def action_unlock(self):
        self.is_locked = False
        self.allow_edit = True

    def _compute_documents_count(self):
        for rec in self:
            rec.documents_count = 0

    def action_add_documents(self):
        view_id = self.env.ref("documents.document_view_kanban").id
        folder_id = self.env.ref("sales_force_support.sales_force_folder").id
        return {
            "name": _("Documents"),
            "type": "ir.actions.act_window",
            "res_model": "documents.document",
            "view_mode": "kanban",
            "view_type": "kanban",
            "views": [(view_id, "kanban")],
            "target": "Current",
            "domain": [
                ("folder_id", "=", folder_id),
                ("partner_id", "=", self.distribution_company_id.id),
            ],
        }

    def _compute_edit_registered_date(self):
        for rec in self:
            if self.env.user.has_group("sales_force_support.group_received_date_edit"):
                rec.edit_registered_date = True
            else:
                rec.edit_registered_date = False

    def _compute_consultants_sales(self):
        for rec in self:
            total = 0
            total_no_sales = 0
            number_of_owing_consultants = 0
            number_of_consultants_with_returns = 0
            for line in rec.payin_line_ids:
                if line.bb_sales != 0 or line.puer_sales != 0:
                    total += 1
                if line.bb_sales == 0 and line.puer_sales == 0:
                    total_no_sales += 1
                if line.comment:
                    number_of_owing_consultants += 1
                if line.bb_returns != 0 or line.puer_returns != 0:
                    number_of_consultants_with_returns += 1
            rec.consultants_sales = total
            rec.consultants_no_sales = total_no_sales
            rec.number_of_owing_consultants = number_of_owing_consultants
            rec.number_of_consultants_with_returns = number_of_consultants_with_returns

    @api.depends("distributor_id", "period")
    def _get_pay_in_filename_payin(self, document_type):
        if not self.distributor_id and not self.period:
            filename = f"{document_type}"
            return filename

        filename = f"{self.period} - {self.distributor_id.known_name} - {self.manager_sales_force_code} - {document_type}"

        return filename

    @api.depends("distributor_id", "period")
    def _get_distribution_pay_ins_filename_payin(self, document_type):
        if not self.distributor_id and not self.period:
            filename = f"{document_type}"
            return filename

        filename = f"{self.period} - {self.distributor_id.known_name} - {document_type}"

        return filename

    @api.depends("state")
    def _allow_edit(self):
        for rec in self:
            rec.allow_edit = False
            if rec.state == "registered":
                rec.allow_edit = True
            if rec.is_locked:
                rec.allow_edit = False
            elif rec.state == "new":
                raise UserError(
                    _(
                        f"You cannot open an unregistered Pay-In Sheet. Please register the Pay-In Sheet first before openning it."
                    )
                )

    def unlink(self):
        for rec in self:
            if rec.state != "new":
                raise UserError(
                    _("You cannot delete {} pay-in sheet.").format(rec.state)
                )
        return super(BbPayinSheet, self).unlink()

    def _compute_consultants_captured(self):
        for rec in self:
            rec.consultants_captured = len(rec.payin_line_ids.ids)

    @api.onchange("payin_line_ids")
    def onchange_for_time(self):
        self.ensure_one()
        if self.state == "registered":
            self.manager_id.lines_capture_start_date = fields.Datetime.now()
            self.write({"lines_capture_start_date": fields.Datetime.now()})
            if not self.capture_start_date:
                self.write(
                    {
                        "capture_start_date": fields.Datetime.now(),
                        "lines_capture_start_date": fields.Datetime.now(),
                    }
                )
            if not self.timesheet_timer_first_start:
                self.write(
                    {
                        "timesheet_timer_first_start": fields.Datetime.now(),
                        "capture_start_date": fields.Datetime.now(),
                        "lines_capture_start_date": fields.Datetime.now(),
                    }
                )
                self.started = True
            if not self.timesheet_timer_start:
                _logger.info("This is self.timesheet_timer_start condition True")
                self.write(
                    {
                        "timesheet_timer_start": fields.Datetime.now(),
                        "lines_capture_start_date": fields.Datetime.now(),
                    }
                )
                self.started = True
            if self.timesheet_timer_pause:
                _logger.info("This is self.timesheet_timer_pasue condition True")
                self.started = True
                self.write({"lines_capture_start_date": fields.Datetime.now()})
                return self.action_timer_resume()

    def action_timer_start(self):
        self.ensure_one()
        self.started = True
        if not self.capture_start_date:
            self.write({"capture_start_date": fields.Datetime.now()})
        if not self.timesheet_timer_first_start:
            self.write(
                {
                    "timesheet_timer_first_start": fields.Datetime.now(),
                    "timesheet_timer_pause": False,
                }
            )

        return self.write(
            {
                "timesheet_timer_start": fields.Datetime.now(),
                "capture_start_date": fields.Datetime.now(),
            }
        )

    def action_timer_pause(self):
        start_time = self.timesheet_timer_start
        if start_time:  # timer was either running
            pause_time = fields.Datetime.now()
            hours_spent = (pause_time - start_time).total_seconds() / 3600
            hours_spent = self._timer_rounding(hours_spent)
            self.write({"capture_time": hours_spent})
            self.write({"timesheet_timer_pause": pause_time, "started": False})

    def action_timer_resume(self):

        new_start = self.timesheet_timer_start + (
            fields.Datetime.now() - self.timesheet_timer_pause
        )
        self.write(
            {
                "timesheet_timer_start": new_start,
                "timesheet_timer_pause": False,
                "started": True,
            }
        )

    def get_duration(self):
        return self.capture_time

    def action_timer_stop(self):
        self.ensure_one()
        self.started = False
        start_time = self.timesheet_timer_start
        if start_time:  # timer was either running or paused
            pause_time = fields.Datetime.now()
            hours_spent = (pause_time - start_time).total_seconds() / 3600
            hours_spent = self._timer_rounding(hours_spent)

            if self.state == "captured" and not self.env["payin.capture.time"].search(
                [("payin_sheet_id", "=", self.id)]
            ):
                self.write(
                    {"capture_time": hours_spent, "timesheet_timer_pause": pause_time}
                )
                self.env["payin.capture.time"].create(
                    {
                        "capture_time": self.capture_time,
                        "capture_start_date": self.capture_start_date,
                        "user_id": self.env.user.id,
                        "date": fields.Datetime.now(),
                        "new_consultants_count": self.new_consultants_count,
                        "consultants_captured": self.consultants_captured,
                        "consultants_sales": self.consultants_sales,
                        "name": self.name,
                        "payin_sheet_id": self.id,
                    }
                )

        return False

    def _timer_rounding(self, minutes_spent):
        minimum_duration = 0
        rounding = 0
        minutes_spent = max(minimum_duration, minutes_spent)
        if rounding and ceil(minutes_spent % rounding) != 0:
            minutes_spent = ceil(minutes_spent / rounding) * rounding
        return minutes_spent

    def get_dist(self, doc):
        doc.wizard = False
        return

    def receive(self):
        if not self.registered_date:
            self.state = "registered"
            self.registered_date = fields.Datetime.now()
            self.received_date = fields.Datetime.now()

    @api.depends(
        "payin_line_ids.bb_brand_total",
        "payin_line_ids.puer_brand_total",
        "payin_line_ids.sub_total",
    )
    def _compute_totals(self):
        for rec in self:
            sub_total = 0
            brand_total = 0
            puer_brand_total = 0
            bb_brand_total = 0
            bb_sales = 0
            bb_returns = 0
            puer_sales = 0
            puer_returns = 0
            for line in rec.payin_line_ids:
                sub_total += line.sub_total
                brand_total += line.bb_brand_total + line.puer_brand_total
                puer_brand_total += line.puer_brand_total
                bb_brand_total += line.bb_brand_total
                bb_sales += line.bb_sales
                bb_returns += line.bb_returns
                puer_sales += line.puer_sales
                puer_returns += line.puer_returns
            rec.sub_total = sub_total
            rec.brand_total = brand_total
            rec.puer_brand_total = puer_brand_total
            rec.bb_brand_total = bb_brand_total
            rec.bb_sales = bb_sales
            rec.bb_returns = bb_returns
            rec.puer_sales = puer_sales
            rec.puer_returns = puer_returns
            rec.grouped_total_captured = sub_total

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

    def capture(self):
        capture = False

        valid_consultant_ids = [
            line
            for line in self.payin_line_ids
            if line.consultant_id and line.consultant_id.id
        ]

        if not len(self.payin_line_ids) == len(valid_consultant_ids):
            raise UserError(
                _(
                    "Ensure that all consultant lines are valid before you complete capturing!"
                )
            )

        for line in self.payin_line_ids:
            if (
                line.bb_sales != 0
                or line.bb_returns != 0
                or line.puer_sales != 0
                or line.puer_returns != 0
                or line.comment
            ):
                capture = True

        if not capture:
            view_id = self.env.ref("sales_force_support.not_captured_wizard_view").id
            capture_id = self.env["not.captured.wizard"].create(
                {"sheet_id": self.id, "do_nothing": True}
            )
            return {
                "name": _("Warning!"),
                "type": "ir.actions.act_window",
                "res_model": "not.captured.wizard",
                "view_mode": "form",
                "view_type": "form",
                "views": [(view_id, "form")],
                "target": "new",
                "res_id": capture_id.id,
            }

        view_id = self.env.ref("sales_force_support.capture_wizard_view").id
        capture_id = self.env["capture.wizard"].create({"sheet_id": self.id})
        return {
            "name": _("Confirm"),
            "type": "ir.actions.act_window",
            "res_model": "capture.wizard",
            "view_mode": "form",
            "view_type": "form",
            "views": [(view_id, "form")],
            "target": "new",
            "res_id": capture_id.id,
        }

    def verify(self):
        self.state = "verified"
        self.is_locked = True

    def get_sheets(self):
        return self.env["bb.payin.sheet"].search(
            [("id", "in", self._context.get("active_ids")), ("state", "=", "new")]
        )

    def _get_company(self):
        for rec in self:
            rec.company_id = self.env.user.company_id.id

    def _get_user(self):
        for rec in self:
            rec.user_id = self.env.user.id

    def pay_in_sheet_lines(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "sales_force_support.pay_sheet_line_export_act_window"
        )
        action["domain"] = [("payin_sheet_id", "=", self.id)]
        return action

    def pay_in_page_totals(self):
        bb_sales_page_total = 0
        bb_returns_page_total = 0
        bb_subtotal_page_total = 0
        puer_sales_page_total = 0
        puer_returns_page_total = 0
        puer_subtotal_page_total = 0
        combined_page_total = 0

        # Get number of pages captured
        # each page has up to 9 consultants pay-in line rows
        payin_lines = self._exclude_zero_sales()
        pages = (len(payin_lines) + 9 // 1) // 9

        page_totals = []
        for page in range(0, pages):

            for line in payin_lines[page * 9 : (page * 9) + 9]:
                bb_sales_page_total += line.bb_sales
                bb_returns_page_total += line.bb_returns
                bb_subtotal_page_total += line.bb_brand_total

                puer_sales_page_total += line.puer_sales
                puer_returns_page_total += line.puer_returns
                puer_subtotal_page_total += line.puer_brand_total

                combined_page_total += line.sub_total

            page_total_dict = {
                "bb_sales_page_total": bb_sales_page_total,
                "bb_returns_page_total": bb_returns_page_total,
                "bb_subtotal_page_total": bb_subtotal_page_total,
                "puer_sales_page_total": puer_sales_page_total,
                "puer_returns_page_total": puer_returns_page_total,
                "puer_subtotal_page_total": puer_subtotal_page_total,
                "combined_page_total": combined_page_total,
            }

            page_totals.append(page_total_dict)

            bb_sales_page_total = 0
            bb_returns_page_total = 0
            bb_subtotal_page_total = 0
            puer_sales_page_total = 0
            puer_returns_page_total = 0
            puer_subtotal_page_total = 0
            combined_page_total = 0

        return page_totals

    @api.model
    def create(self, vals):

        res = super(BbPayinSheet, self).create(vals)

        if not res.name:
            res.name = (
                res.get_date(res.date)
                + " / "
                + res.manager_id.name
                + " / "
                + res.manager_id.sales_force_code
            )
        return res

    def empty_rows(self):
        list_length = len(self.payin_line_ids)
        num_of_rows = ceil((list_length + 20) / 9) * 9 - list_length
        return [None for i in range(num_of_rows)]

    def empty_rows2(self):
        return [None for i in range(18)]

    @api.model
    def get_views(self, views, options=None):
        result = super().get_views(views, options)
        if options and options.get("toolbar"):
            list_view = result["views"].get("list")
            if (
                list_view
                and list_view.get("toolbar")
                and list_view["toolbar"].get("print")
                and list_view["toolbar"].get("action")
            ):
                view_list_name = (
                    self.env["ir.ui.view"]
                    .sudo()
                    .browse(result["views"]["list"]["id"])
                    .name
                )

                for action in list_view["toolbar"]["action"]:
                    action_id = action.get("id")
                    xml_id = (
                        self.env["ir.actions.act_window"]
                        .sudo()
                        .browse(action_id)
                        .xml_id
                    )
                    if xml_id:
                        if view_list_name == "bb.payin.sheet.tree.status_update":
                            list_view["toolbar"]["action"].remove(action)
                            list_view["toolbar"]["print"] = []

                        if (
                            view_list_name == "bb.payin.sheet.tree"
                            and xml_id == "sales_force_support.action_change_state"
                        ):
                            list_view["toolbar"]["action"].remove(action)

                for print in list_view["toolbar"]["print"]:
                    print_id = print.get("id")
                    xml_id = (
                        self.env["ir.actions.report"].sudo().browse(print_id).xml_id
                    )
                    if (
                        view_list_name
                        in ("bb.payin.sheet.tree.new, bb.payin.sheet.tree")
                        and xml_id == "sales_force_support.action_report_captured_payin_sheets"
                    ):
                        list_view["toolbar"]["print"].remove(print)
        return result


class BbPayinSheetLine(models.Model):
    _name = "bb.payin.sheet.line"
    _description = "Pay-In Sheet Lines"

    payin_sheet_id = fields.Many2one("bb.payin.sheet", "Payin Manager Header")
    bb_sales = fields.Float("BB Sales")
    bb_returns = fields.Float("BB Returns")
    puer_sales = fields.Float("Puer Sales")
    puer_returns = fields.Float("Puer Returns")
    comment = fields.Char("Owing/Comments")
    consultant_id = fields.Many2one("sf.member", "Consultant")
    sales_force_code = fields.Char("SFM Code", related="consultant_id.sales_force_code")
    sub_total = fields.Float("Sub Total", compute="_compute_totals", store=True)
    bb_brand_total = fields.Float("BB Total", compute="_compute_totals", store=True)
    puer_brand_total = fields.Float("Puer Total", compute="_compute_totals", store=True)
    captured = fields.Boolean()
    timesheet_timer_first_start = fields.Datetime(
        "Timesheet Timer First Use", readonly=True
    )
    timesheet_timer_last_stop = fields.Datetime(
        "Timesheet Timer Last Use", readonly=True
    )

    lines_capture_stop_date = fields.Datetime("Lines Stop Timer")
    lines_capture_start_date = fields.Datetime("Lines Timer")
    time_in_secs = fields.Float("Time in seconds")

    @api.onchange("bb_sales", "bb_returns", "puer_sales", "puer_returns", "comment")
    def onchange_all_fields_to_get_time(self):
        if not self.consultant_id.lines_capture_start_date:
            self.consultant_id.lines_capture_start_date = fields.Datetime.now()
        self.consultant_id.lines_capture_stop_date = fields.Datetime.now()

    def unlink(self):
        for rec in self:
            res_id = rec.payin_sheet_id.id
            user_id = self.env.user
            if res_id and rec.payin_sheet_id.state in ["captured", "verified"]:
                message = self.env["mail.message"].create(
                    {
                        "author_id": user_id.partner_id.id,
                        "model": "bb.payin.sheet",
                        "body": rec.consultant_id.display_name
                        + " Line "
                        + "Deleted by "
                        + user_id.name,
                        "res_id": res_id,
                    }
                )
        return super(BbPayinSheetLine, self).unlink()

    @api.depends("bb_sales", "bb_returns", "puer_sales", "puer_returns")
    def _compute_totals(self):
        for rec in self:
            sub_total = 0
            bb_brand_total = 0
            puer_brand_total = 0

            bb_brand_total += rec.bb_sales - abs(rec.bb_returns)
            puer_brand_total += rec.puer_sales - abs(rec.puer_returns)
            sub_total += bb_brand_total + puer_brand_total

            rec.sub_total = sub_total
            rec.puer_brand_total = puer_brand_total
            rec.bb_brand_total = bb_brand_total

    def write(self, vals):
        res = "check"
        bb_total = self.bb_sales - self.bb_returns
        puer_total = self.puer_sales - self.puer_returns
        time_in_secs = 0.00

        # check if sales and returns are negative and raise a UserError
        for key in ["bb_sales", "bb_returns", "puer_sales", "puer_returns"]:
            if key in vals and vals[key] < 0:
                raise UserError(
                    _(
                        f"You cannot enter a negative value in {self._fields[key].string} on {self.consultant_id.name} - {self.sales_force_code}"
                    )
                )

        if not self.captured:
            vals["captured"] = True
        if (
            self.consultant_id.lines_capture_stop_date
            and self.consultant_id.lines_capture_start_date
        ):
            vals["time_in_secs"] = round(
                (
                    self.consultant_id.lines_capture_stop_date
                    - self.consultant_id.lines_capture_start_date
                ).total_seconds(),
                2,
            )
        self.consultant_id.lines_capture_stop_date = False
        self.consultant_id.lines_capture_start_date = False

        for record in self:
            if record.payin_sheet_id.state in ["captured", "verified"]:
                personal_history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "=", record.payin_sheet_id.payin_date),
                        ("employee_id", "=", record.consultant_id[0].id),
                    ],
                    limit=1,
                )
                if not personal_history_id:
                    personal_history_id = self.env["bb.payin.history"].create(
                        {
                            "payin_date": record.payin_sheet_id.payin_date,
                            "employee_id": record.consultant_id.id,
                            "active_status": record.consultant_id.active_status,
                            "current_job_id": record.consultant_id.job_id.id,
                            "manager_code": record.consultant_id.manager_id.sales_force_code,
                            # Change From v14 after upgrade to v17
                            "distributor_code": record.consultant_id.related_distributor_id.sales_force_code,
                            "manager_id": record.consultant_id.manager_id.id,
                        }
                    )

                bb_sales_old = self.bb_brand_total
                puer_sales_old = self.puer_brand_total
                res = super(BbPayinSheetLine, self).write(vals)

                bb_sales_new = self.bb_brand_total
                puer_sales_new = self.puer_brand_total
                if bb_sales_old != bb_sales_new or puer_sales_new != puer_sales_old:
                    record.payin_sheet_id.changed = True
                    record.payin_chaged(
                        bb_sales_old, puer_sales_old, bb_sales_new, puer_sales_new
                    )

        if res == "check":
            res = super(BbPayinSheetLine, self).write(vals)

        if self.payin_sheet_id.state in ["verified", "captured"]:
            if vals.get("puer_sales") or vals.get("puer_returns"):
                res_id = self.payin_sheet_id.id
                user_id = self.env.user
                if res_id:
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "bb.payin.sheet",
                            "body": self.consultant_id.display_name
                            + " Puer Total changed from "
                            + str(puer_total)
                            + "0 to "
                            + str(self.puer_brand_total)
                            + "0 by "
                            + user_id.display_name,
                            "res_id": res_id,
                        }
                    )

            if vals.get("bb_sales") or vals.get("bb_returns"):
                res_id = self.payin_sheet_id.id
                user_id = self.env.user
                if res_id:
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "bb.payin.sheet",
                            "body": self.consultant_id.display_name
                            + " BB Total changed from "
                            + str(bb_total)
                            + "0 to "
                            + str(self.bb_brand_total)
                            + "0 by "
                            + user_id.display_name,
                            "res_id": res_id,
                        }
                    )

            res_id = self.payin_sheet_id.id
            user_id = self.env.user
            if res_id:
                if vals.get("captured"):
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "bb.payin.sheet",
                            "body": user_id.display_name
                            + " captured "
                            + self.consultant_id.display_name
                            + " Sales Lines in "
                            + str(int(vals["time_in_secs"]))
                            + " seconds.",
                            "res_id": res_id,
                        }
                    )
                else:
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "bb.payin.sheet",
                            "body": user_id.display_name
                            + " edited "
                            + self.consultant_id.display_name
                            + " Sales Lines in "
                            + str(int(vals["time_in_secs"]))
                            + " seconds.",
                            "res_id": res_id,
                        }
                    )

        if self.payin_sheet_id.started:
            self.payin_sheet_id.action_timer_pause()
        return res

    @api.model
    def create(self, vals):
        res = super(BbPayinSheetLine, self).create(vals)
        if res.payin_sheet_id.state == "registered":
            res.payin_sheet_id.new_consultants_count += 1
        if (
            res.bb_sales != 0
            or res.bb_returns != 0
            or res.puer_sales != 0
            or res.puer_returns != 0
            or res.comment
        ):
            if not res.payin_sheet_id.manager_id.partner_id:
                applicant = self.env["sf.recruit"].search(
                    [("emp_id", "=", res.payin_sheet_id.manager_id.id)]
                )
                if not applicant:
                    applicant = self.env["sf.recruit"].search(
                        [
                            ("emp_id", "=", res.payin_sheet_id.manager_id.id),
                            ("active", "=", False),
                        ]
                    )
                if applicant:
                    res.payin_sheet_id.manager_id.partner_id = applicant.partner_id.id

        if res.payin_sheet_id.state != "new":
            res.payin_sheet_id.new_consultants_count += 1

        if res.payin_sheet_id.state in ["captured", "verified"]:
            personal_history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "=", res.payin_sheet_id.payin_date),
                    ("employee_id", "=", res.consultant_id[0].id),
                ],
                limit=1,
            )
            if not personal_history_id:
                personal_history_id = self.env["bb.payin.history"].create(
                    {
                        "payin_date": res.payin_sheet_id.payin_date,
                        "employee_id": res.consultant_id.id,
                        "active_status": res.consultant_id.active_status,
                        "current_job_id": res.consultant_id.job_id.id,
                        "manager_code": res.consultant_id.manager_id.sales_force_code,
                        # Change From v14 after upgrade to v17
                        "distributor_code": res.consultant_id.related_distributor_id.sales_force_code,
                        "manager_id": res.consultant_id.manager_id.id,
                        "personal_bbb_sale": res.bb_brand_total,
                        "personal_puer_sale": res.puer_brand_total,
                    }
                )

            bb_sales_old = 0
            puer_sales_old = 0
            bb_sales_new = 0
            puer_sales_new = 0
            if vals.get("bb_sales"):
                bb_sales_new = res.bb_brand_total
            if vals.get("puer_sales"):
                puer_sales_new = res.puer_brand_total
            if (
                vals.get("bb_sales")
                or vals.get("bb_returns")
                or vals.get("puer_sales")
                or vals.get("puer_returns")
            ):
                res.payin_sheet_id.changed = True
                res.payin_chaged(
                    bb_sales_old, puer_sales_old, bb_sales_new, puer_sales_new
                )
        return res

    def payin_chaged(self, bb_sales_old, puer_sales_old, bb_sales_new, puer_sales_new):
        # Consultant update
        for consultant_history in self.env["bb.payin.history"].search(
            [
                ("payin_date", "=", self.payin_sheet_id.payin_date),
                ("employee_id", "=", self.consultant_id.id),
            ],
            limit=1,
        ):
            consultant_history.write({"personal_bbb_sale": bb_sales_new})
            consultant_history.personal_bbb_sale = bb_sales_new
            consultant_history.write({"personal_puer_sale": puer_sales_new})
            consultant_history.personal_puer_sale = puer_sales_new
            consultant_history.changed = True

        self.payin_sheet_id.action_timer_stop()


class PayinDistributor(models.Model):
    _name = "payin.distributor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In Sheet Distributor Summary"

    captured_by = fields.Char(string="Captured By", compute="_get_captured_by")
    payin_line_ids = fields.One2many(
        "payin.distributor.line", "payin_sheet_id", "Lines"
    )
    distributor_id = fields.Many2one("sf.member", "Distributor")
    distributor_known_name = fields.Char(string="Distributor Known Name")
    distribution_company_id = fields.Many2one(
        "res.partner", string="Distribution", store=True
    )
    distributor_sales_force_code = fields.Char(
        related="distributor_id.sales_force_code", string="Distributor SFM Code"
    )
    distribution_known_name = fields.Char(
        related="distributor_id.known_name", string="Distribution Name"
    )
    date = fields.Date("Month/Year")
    name = fields.Char("Name")
    state = fields.Selection(
        [
            ("new", "New"),
            ("registered", "Registered"),
            ("captured", "Captured"),
            ("verified", "Verified"),
        ],
        string="Status",
        default="new",
        tracking=3,
    )
    company_id = fields.Many2one(
        "res.company", string="Company", compute="_get_company"
    )
    user_id = fields.Many2one("res.users", string="Responsible", compute="_get_user")
    total_captured = fields.Float(
        "Total Captured Pay-In Sheets Sales", compute="_compute_total_captured"
    )
    payin_date = fields.Date("Capture Period")
    registered_date = fields.Date("Registered Date")
    received_date = fields.Date("Received Date", tracking=True)
    timesheet_timer_start = fields.Datetime("Timesheet Timer Start", default=None)
    timesheet_timer_pause = fields.Datetime("Timesheet Timer Last Pause")
    timesheet_timer_first_start = fields.Datetime(
        "Timesheet Timer First Use", readonly=True
    )
    timesheet_timer_last_stop = fields.Datetime(
        "Timesheet Timer Last Use", readonly=True
    )
    consultants_captured = fields.Integer(
        "No. of Managers Captured", compute="_compute_consultants_captured"
    )
    capture_time = fields.Float("Time to Capture")
    consultants_sales = fields.Integer(
        "No. of Managers With Sales", compute="_compute_no_of_manager_sales"
    )
    consultants_no_sales = fields.Integer(
        "No. of Managers With No Sales", compute="_compute_no_of_manager_sales"
    )
    distributor = fields.Integer(string="Distributor ID")
    started = fields.Boolean()
    total_actual_sales = fields.Float(
        "Total Distribution Sales", compute="_compute_actual_sales"
    )
    total_difference = fields.Float("Total Difference", compute="_compute_difference")
    capture_start_date = fields.Date("Capture Start Date")
    comments = fields.Char("Comments")
    lines_capture_start_date = fields.Datetime("Lines Timer")
    lines_capture_stop_date = fields.Datetime("Lines Stop Timer")
    no_of_pages = fields.Integer("No. of Pages Registered", tracking=True)
    documents_count = fields.Integer(
        "Documents Count", compute="_compute_documents_count"
    )
    period = fields.Char(string="Capture Period", compute="_compute_period", store=True)
    is_locked = fields.Boolean("Is locked?")
    allow_edit = fields.Boolean("Allow Edit Distributor Summary", compute="_allow_edit")
    distributor_mobile = fields.Char(
        related="distributor_id.mobile", string="Distributor mobile"
    )

    # New field to track received payin-sheet based on number of pages
    is_no_sales = fields.Boolean(string="No Sales", tracking=True, default=False)
    changed = fields.Boolean("Distributor Summary changed", default=False)
    grouped_total_captured = fields.Float("Total Captured")

    @api.onchange("x_studio_status_update")
    def _onchange_x_studio_status_update(self):
        formatted_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.x_studio_latest_status_update = formatted_datetime

    @api.depends("payin_line_ids")
    def _exclude_zero_sales(self):
        filtered_records = []
        for rec in self.payin_line_ids:
            if rec.actual_sales != 0:
                filtered_records.append(rec)
        return filtered_records

    def _get_captured_by(self):
        self._cr.execute(
            """
            SELECT rp.name
            FROM mail_tracking_value mtv
            LEFT JOIN mail_message mm ON mm.id = mtv.mail_message_id
            LEFT JOIN res_partner rp ON rp.id = mm.author_id
            LEFT JOIN ir_model_fields f ON f.id = mtv.field_id
            WHERE f.name = 'state'
            AND mm.model = 'payin.distributor'
            AND mtv.old_value_char = 'Registered'
            AND mm.res_id = %s
            ORDER BY mtv.id DESC
            LIMIT 1
        """,
            (self.id,),
        )
        captured_by_rec = self._cr.fetchone()
        self.captured_by = captured_by_rec[0] if captured_by_rec else ""

    @api.depends("distributor_id", "period")
    def _get_pay_in_filename(self, document_type):
        if not self.distributor_id and not self.period:
            filename = f"{document_type}"
            return filename
        filename = (
            f" {self.period} - {self.distributor_id.known_name} - {document_type}"
        )
        return filename

    def action_lock(self):
        self.is_locked = True
        self.allow_edit = False

    def empty_distributor_rows(self):
        list_length = len(self.payin_line_ids)
        _logger.info("list lrngth %s", list_length)
        num_of_rows = ceil((list_length + 12) / 9) * 9 - list_length
        _logger.info("this is num_of_rows %s", num_of_rows)
        return [None for i in range(num_of_rows)]

    def empty_distributor_rows2(self):
        return [None for i in range(18)]

    def action_unlock(self):
        self.is_locked = False
        self.allow_edit = True

    @api.depends("state")
    def _allow_edit(self):
        for rec in self:
            if rec.is_locked:
                rec.allow_edit = False
            elif rec.state == "new":
                raise UserError(
                    _(
                        f"You cannot open an unregistered Distributor Summary. Please register the Distributor Summary first before openning it."
                    )
                )

    @api.depends("date")
    def _compute_period(self):
        for rec in self:
            rec.period = " "
            if rec.date:
                rec.period = rec.get_date(rec.date)

    def _compute_total_captured(self):
        for rec in self:
            total = 0
            for payin in self.env["bb.payin.sheet"].search(
                [
                    ("date", "=", rec.date),
                    ("distributor_id", "=", rec.distributor_id.id),
                    ("state", "in", ("captured", "verified")),
                ]
            ):
                total += payin.sub_total
            rec.total_captured = total
            rec.grouped_total_captured = rec.total_captured

    def _compute_actual_sales(self):
        for rec in self:
            total = 0
            for line in rec.payin_line_ids:
                total += abs(line.actual_sales)
            rec.total_actual_sales = total

    def _compute_difference(self):
        for rec in self:
            total = 0
            for line in rec.payin_line_ids:
                total += line.sales_difference
            rec.total_difference = total

    def _compute_documents_count(self):
        for rec in self:
            rec.documents_count = 0

    def distributor_summary_page_totals(self):
        distribution_sales_page_total = 0
        captured_page_total = 0
        difference_total = 0
        combined_page_total = 0

        payin_lines = self._exclude_zero_sales()
        pages = (len(payin_lines) + 8 // 1) // 8

        page_totals = []
        for page in range(0, pages):

            for line in payin_lines[page * 8 : (page * 8) + 8]:
                distribution_sales_page_total += line.actual_sales
                captured_page_total += line.total_captured
                difference_total += line.sales_difference

            page_total_dict = {
                "distribution_sales_page_total": distribution_sales_page_total,
                "captured_page_total": captured_page_total,
                "difference_total": difference_total,
            }

            page_totals.append(page_total_dict)

            distribution_sales_page_total = 0
            captured_page_total = 0
            difference_total = 0
        return page_totals

    def distributor_total_page_calculate(self):
        list_length = len(self.payin_line_ids)
        blank_rows_require = ceil((list_length + 12) / 9) * 9 - list_length
        total_rows = list_length + blank_rows_require

        calculate_pages = total_rows // 9
        _logger.info("calculated page is in calculated function %s", calculate_pages)
        return calculate_pages

    def _compute_consultants_captured(self):
        for rec in self:
            rec.consultants_captured = len(rec.payin_line_ids.ids)

    @api.onchange("payin_line_ids")
    def onchange_for_time(self):
        self.ensure_one()
        self.write({"lines_capture_start_date": fields.Datetime.now()})
        if not self.capture_start_date:
            self.write(
                {
                    "capture_start_date": fields.Datetime.now(),
                    "lines_capture_start_date": fields.Datetime.now(),
                }
            )
        if not self.timesheet_timer_first_start:
            self.write(
                {
                    "timesheet_timer_first_start": fields.Datetime.now(),
                    "capture_start_date": fields.Datetime.now(),
                    "lines_capture_start_date": fields.Datetime.now(),
                }
            )
            self.started = True
        if not self.timesheet_timer_start:
            self.write(
                {
                    "timesheet_timer_start": fields.Datetime.now(),
                    "lines_capture_start_date": fields.Datetime.now(),
                }
            )
        if self.timesheet_timer_pause:
            self.started = True
            self.write({"lines_capture_start_date": fields.Datetime.now()})
            return self.action_timer_resume()

    def action_timer_start(self):
        self.ensure_one()
        if not self.capture_start_date:
            self.write({"capture_start_date": fields.Datetime.now()})
        if not self.timesheet_timer_first_start:
            self.write(
                {
                    "timesheet_timer_first_start": fields.Datetime.now(),
                    "timesheet_timer_pause": False,
                }
            )
        return self.write(
            {
                "timesheet_timer_start": fields.Datetime.now(),
                "capture_start_date": fields.Datetime.now(),
            }
        )

    def action_timer_pause(self):
        start_time = self.timesheet_timer_start
        if start_time:  # timer was either running
            pause_time = fields.Datetime.now()
            hours_spent = (pause_time - start_time).total_seconds() / 3600
            hours_spent = self._timer_rounding(hours_spent)
            self.write({"capture_time": hours_spent})
            self.write({"timesheet_timer_pause": pause_time, "started": False})

    def action_timer_resume(self):
        new_start = self.timesheet_timer_start + (
            fields.Datetime.now() - self.timesheet_timer_pause
        )
        self.write(
            {
                "timesheet_timer_start": new_start,
                "timesheet_timer_pause": False,
                "started": True,
            }
        )

    def action_timer_stop(self):
        self.ensure_one()
        self.started = False
        start_time = self.timesheet_timer_start
        if start_time:  # timer was either running or paused
            pause_time = fields.Datetime.now()
            hours_spent = (pause_time - start_time).total_seconds() / 3600
            hours_spent = self._timer_rounding(hours_spent)

            if self.state == "captured" and not self.env[
                "payin.distributor.capture.time"
            ].search([("payin_sheet_id", "=", self.id)]):
                self.write(
                    {"capture_time": hours_spent, "timesheet_timer_pause": pause_time}
                )
                self.env["payin.distributor.capture.time"].create(
                    {
                        "capture_time": self.capture_time,
                        "capture_start_date": self.capture_start_date,
                        "user_id": self.env.user.id,
                        "date": fields.Datetime.now(),
                        "consultants_captured": self.consultants_captured,
                        "consultants_sales": self.consultants_sales,
                        "name": self.name,
                        "payin_sheet_id": self.id,
                    }
                )

        return False

    def _timer_rounding(self, minutes_spent):
        minimum_duration = 0
        rounding = 0
        minutes_spent = max(minimum_duration, minutes_spent)
        if rounding and ceil(minutes_spent % rounding) != 0:
            minutes_spent = ceil(minutes_spent / rounding) * rounding
        return minutes_spent

    def unlink(self):
        if self.state != "new":
            raise UserError(_("You cannot delete {} pay-in sheet.").format(self.state))
        return super(PayinDistributor, self).unlink()

    def recieve(self):
        if self.state == "new":
            self.state = "registered"
            self.registered_date = fields.Datetime.now()
            self.received_date = fields.Datetime.now()
        else:
            raise UserError(_("You cannot receive {} pay-in sheet.").format(self.state))

    def verify(self):
        # Check if all manager payin sheets are in verified state
        manager_count = self.env["bb.payin.sheet"].search(
            [("date", "=", self.date), ("distributor_id", "=", self.distributor_id.id)]
        )

        manager_verified_count = [
            verified_payin
            for verified_payin in manager_count
            if verified_payin.state == "verified"
        ]

        if not len(manager_count) == len(manager_verified_count):
            raise UserError(
                _(
                    "You cannot verify capturing before all manager Pay-In Sheets are verified."
                )
            )
        else:
            self.state = "verified"
            self.is_locked = True

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

    def capture(self):
        capture = False

        for line in self.payin_line_ids:
            if line.actual_sales != 0 or line.comment:
                capture = True

        if not capture:
            view_id = self.env.ref("sales_force_support.not_captured_wizard_view").id
            capture_id = self.env["not.captured.wizard"].create(
                {"sheet_id_dist": self.id, "do_nothing": True}
            )
            return {
                "name": _("Warning!"),
                "type": "ir.actions.act_window",
                "res_model": "not.captured.wizard",
                "view_mode": "form",
                "view_type": "form",
                "views": [(view_id, "form")],
                "target": "new",
                "res_id": capture_id.id,
            }

        self.action_timer_stop()
        view_id = self.env.ref("sales_force_support.capture_wizard_view_dist").id
        capture_id = self.env["capture.wizard"].create({"sheet_id_dist": self.id})
        return {
            "name": _("Confirm"),
            "type": "ir.actions.act_window",
            "res_model": "capture.wizard",
            "view_mode": "form",
            "view_type": "form",
            "views": [(view_id, "form")],
            "target": "new",
            "res_id": capture_id.id,
        }

    def _get_company(self):
        for rec in self:
            rec.company_id = self.env.user.company_id.id

    def _get_user(self):
        for rec in self:
            rec.user_id = self.env.user.id

    @api.model
    def create(self, vals):
        res = super(PayinDistributor, self).create(vals)

        if not res.name:
            res.name = (
                res.get_date(res.date)
                + " / "
                + res.distributor_id.name
                + " / "
                + res.distributor_sales_force_code
            )
        return res

    def empty_rows(self):
        return [None for i in range(12)]

    @api.model
    def get_views(self, views, options=None):
        result = super().get_views(views, options)
        if options and options.get("toolbar"):
            list_view = result["views"].get("list")
            if (
                list_view
                and list_view.get("toolbar")
                and list_view["toolbar"].get("print")
                and list_view["toolbar"].get("action")
            ):
                view_list_name = (
                    self.env["ir.ui.view"]
                    .sudo()
                    .browse(result["views"]["list"]["id"])
                    .name
                )

                for action in list_view["toolbar"]["action"]:
                    action_id = action.get("id")
                    xml_id = (
                        self.env["ir.actions.act_window"]
                        .sudo()
                        .browse(action_id)
                        .xml_id
                    )
                    if xml_id:
                        if view_list_name == "payin.distributor.tree.status_update":
                            list_view["toolbar"]["action"].remove(action)
                            list_view["toolbar"]["print"] = []

                        if (
                            view_list_name == "payin.distributor.tree"
                            and xml_id == "sales_force_support.action_change_state_distributor"
                        ):
                            list_view["toolbar"]["action"].remove(action)

                for print in list_view["toolbar"]["print"]:
                    _logger.info("print %s", print)
                    print_id = print.get("id")
                    xml_id = (
                        self.env["ir.actions.report"].sudo().browse(print_id).xml_id
                    )
                    if (
                        view_list_name == "payin.distributor.tree.new"
                        and xml_id
                        == "sales_force_support.action_report_captured_payin_distributor"
                    ):
                        list_view["toolbar"]["print"].remove(print)
        return result

    def _compute_no_of_manager_sales(self):
        for rec in self:
            total = 0
            total_no_sales = 0
            for line in rec.payin_line_ids:
                if line.total_captured != 0:
                    total += 1
                if line.total_captured == 0:
                    total_no_sales += 1
            rec.consultants_sales = total
            rec.consultants_no_sales = total_no_sales

    def write(self, vals):
        res = super(PayinDistributor, self).write(vals)

        return res


class PayinDistributorLines(models.Model):
    _name = "payin.distributor.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In Sheet Distributor Summary Lines"

    payin_sheet_id = fields.Many2one("payin.distributor", "Payin Distributor Header")
    actual_sales = fields.Float("Distribution Sales")
    comment = fields.Char("Comments")
    manager_id = fields.Many2one(
        "sf.member", "Manager", domain=lambda self: self.onchange_field_manager_id()
    )
    sales_force_code = fields.Char("SFM Code", related="manager_id.sales_force_code")
    total_captured = fields.Float(
        "Captured Pay-In Sheets Sales", compute="_compute_total_captured"
    )

    # New field to calculate the difference between total_captured and actual_sales
    sales_difference = fields.Float("Difference", compute="_compute_sales_difference")
    time_in_secs = fields.Float("Time in seconds")

    def _compute_total_captured(self):
        for rec in self:
            total = 0
            payin = self.env["bb.payin.sheet"].search(
                [
                    ("date", "=", rec.payin_sheet_id.date),
                    ("manager_id", "=", rec.manager_id.id),
                    ("state", "in", ("captured", "verified")),
                ],
                limit=1,
            )
            if payin:
                total = payin.sub_total
            rec.total_captured = total

    @api.depends("total_captured", "actual_sales")
    def _compute_sales_difference(self):
        for rec in self:
            rec.sales_difference = rec.total_captured - rec.actual_sales

    @api.onchange("manager_id")
    def onchange_field_manager_id(self):
        return {
            "domain": {
                "manager_id": [
                    (
                        "id",
                        "not in",
                        self.payin_sheet_id.payin_line_ids.mapped("manager_id").ids,
                    ),
                    (
                        "job_id.name",
                        "in",
                        [
                            "Manager",
                            "Prospective Manager",
                            "Prospective Distributor",
                            "Distributor",
                        ],
                    ),
                ]
            }
        }

    def _track_qty_received(self, values):
        self.ensure_one()
        if self.payin_sheet_id.state == "captured":
            self.payin_sheet_id._message_log_with_view(
                "sales_force_support.track_payin_line_changed_template",
                render_values={"applicant": self.payin_sheet_id},
            )

    @api.onchange("actual_sales", "comment")
    def onchange_all_fields_to_get_time(self):
        for rec in self:
            rec.manager_id.lines_capture_start_date = fields.Datetime.now()

    @api.model
    def write(self, vals):
        # check if sales and returns are negative and raise a UserError
        for key in ["actual_sales"]:
            if key in vals and vals[key] < 0:
                raise UserError(
                    _(
                        f"You cannot enter a negative value in {self._fields[key].string} on {self.manager_id.name} - {self.sales_force_code}"
                    )
                )

        for rec in self:
            sales_captured = rec.actual_sales
            rec.manager_id.lines_capture_stop_date = fields.Datetime.now()
            if (
                rec.manager_id.lines_capture_stop_date
                and rec.manager_id.lines_capture_start_date
            ):
                vals["time_in_secs"] = round(
                    (
                        rec.manager_id.lines_capture_stop_date
                        - self.manager_id.lines_capture_start_date
                    ).total_seconds(),
                    2,
                )
            rec.manager_id.lines_capture_stop_date = False
            rec.manager_id.lines_capture_start_date = False

        if self.payin_sheet_id.started:
            self.payin_sheet_id.action_timer_pause()

        res = super(PayinDistributorLines, self).write(vals)
        if self.payin_sheet_id.state in ["verified", "captured"]:
            if vals.get("actual_sales"):
                if sales_captured != vals["actual_sales"]:
                    self.payin_sheet_id.changed = True
                res_id = self.payin_sheet_id.id
                user_id = self.env.user
                if res_id:
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "payin.distributor",
                            "body": self.manager_id.display_name
                            + " Actual Sales changed from "
                            + str(sales_captured)
                            + "0 to "
                            + str(self.actual_sales)
                            + "0 by "
                            + user_id.display_name,
                            "res_id": res_id,
                        }
                    )
                    message = self.env["mail.message"].create(
                        {
                            "author_id": user_id.partner_id.id,
                            "model": "payin.distributor",
                            "body": user_id.display_name
                            + " edited "
                            + self.manager_id.display_name
                            + " Sales Lines in "
                            + str(int(vals["time_in_secs"]))
                            + " second(s).",
                            "res_id": res_id,
                        }
                    )
        self.payin_sheet_id.action_timer_stop()

        return res


class PayinCaptureTime(models.Model):
    _name = "payin.capture.time"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In Sheet Capture Time"

    payin_sheet_id = fields.Many2one("bb.payin.sheet", "Pay-In Sheet")
    user_id = fields.Many2one("res.users")
    consultants_captured = fields.Integer("Number of Consultants Captured")
    capture_time = fields.Float("Time to Capture")
    capture_start_date = fields.Date("Capture Start Date")
    consultants_sales = fields.Integer("Number of Consultants With Sales")
    new_consultants_count = fields.Float("New Consultants Captured")
    date = fields.Date("Date")
    name = fields.Char("Pay-In Sheet")


class PayinDistributorCaptureTime(models.Model):
    _name = "payin.distributor.capture.time"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Pay-In Sheet Distributor Summary Capture Time"

    payin_sheet_id = fields.Many2one("payin.distributor", "Pay-In Sheet")
    user_id = fields.Many2one("res.users")
    consultants_captured = fields.Integer("Number of Consultants Captured")
    capture_time = fields.Float("Time to Capture")
    capture_start_date = fields.Date("Capture Start Date")
    consultants_sales = fields.Integer("Number of Consultants With Sales")
    date = fields.Date("Date")
    name = fields.Char("Pay-In Sheet Distributor Summary Name")
