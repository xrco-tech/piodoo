# -*- coding: utf-8 -*-
# NEW standalone model — replaces hr.employee for Sales Force Members.
# Sources merged:
#   - bbb_sales_force_genealogy/models/hr_employee.py
#   - botle_buhle_custom/models/hr_employee.py
#   - bb_allocate/models/hr_employee.py
#
# Key transformations:
#   - _inherits = {"res.partner": "partner_id"}  (no _inherit from hr.employee)
#   - All Many2one("hr.employee") → Many2one("sf.member")
#   - All Many2one("hr.applicant") → Many2one("sf.recruit")
#   - job_id (Many2one hr.job) → genealogy (Selection)
#   - job_name computed from genealogy selection value
#   - previous_genealogy (Many2one hr.job) → previous_genealogy (Selection)
#   - related_stage_id (Many2one hr.job) → related_genealogy (Selection alias of genealogy)
#   - Raw SQL: hr_employee table → sf_member
#   - Sync config params: bbb_sales_force_genealogy.* → sales_force_support.*
#   - XML IDs: botle_buhle_custom.* → sales_force_support.* (Phase 7 final sweep)

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
import re
import requests
import json
from datetime import datetime, timedelta
import random
import string

_logger = logging.getLogger(__name__)


# Genealogy levels — canonical list shared across the module
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


class SfMember(models.Model):
    _name = "sf.member"
    _description = "Sales Force Member"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _inherits = {"res.partner": "partner_id"}
    _order = "name"

    # ── Partner delegation ────────────────────────────────────────────────────
    # Fields on res.partner (name, email, mobile, phone, street, street2, city,
    # state_id, country_id, zip, image_1920, sa_id, passport, first_name,
    # last_name, known_name, mobile_2, suburb, birth_date, gender, nationality,
    # bad_debts, credit_score, compuscan_*, unverified_*, consumerview_ref,
    # distribution_id on partner, etc.) are inherited via delegation and must
    # NOT be redeclared here.
    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        string="Partner",
        auto_join=True,
    )

    # ── Remote synchronisation ─────────────────────────────────────────────────
    remote_id = fields.Integer(string="Remote Primary Key", tracking=True)
    last_outbound_sync_date = fields.Datetime(string="Last Outbound Sync Date")
    last_inbound_sync_date = fields.Datetime(string="Last Inbound Sync Date")

    # ── Hierarchy / Relations ─────────────────────────────────────────────────
    parent_id = fields.Many2one(
        "sf.member",
        "Parent SFM",
        ondelete="set null",
        help="Hierarchical parent (e.g. Distributor above Managers).",
    )
    manager_id = fields.Many2one(
        "sf.member",
        "Manager",
        ondelete="set null",
        tracking=True,
    )
    recruiter_id = fields.Many2one(
        "sf.member",
        "Recruited By",
        tracking=True,
    )
    promoter_id = fields.Many2one(
        "sf.member",
        "Promoted By",
        tracking=True,
    )
    demoter_id = fields.Many2one(
        "sf.member",
        "Demoted By",
        tracking=True,
    )
    consultant_id = fields.Many2one(
        "sf.member",
        "Consultant",
    )
    related_distributor_id = fields.Many2one(
        "sf.member",
        "Distributor",
        compute="_compute_related_distributor_id",
        store=True,
        tracking=True,
    )
    related_prospective_manager_id = fields.Many2one(
        "sf.member",
        "Related Prospective Manager",
        tracking=True,
    )
    related_prospective_distributor_id = fields.Many2one(
        "sf.member",
        "Related Prospective Distributor",
        tracking=True,
    )
    previous_manager_id = fields.Many2one(
        "sf.member",
        "Previous Manager",
        tracking=True,
    )
    previous_distributor_id = fields.Many2one(
        "sf.member",
        "Previous Distributor",
        tracking=True,
    )

    # ── Distribution ──────────────────────────────────────────────────────────
    distribution_id = fields.Many2one(
        "sf.distribution",
        string="Distribution",
        compute="compute_distribution_id",
        store=True,
        recursive=True,
    )

    # ── Genealogy (replaces job_id / hr.job) ──────────────────────────────────
    genealogy = fields.Selection(
        GENEALOGY_LEVELS,
        string="Genealogy",
        tracking=True,
    )
    # Backward-compat alias used in views / reports
    job_name = fields.Char(
        "Genealogy",
        compute="_compute_job_name",
        store=True,
        tracking=True,
    )
    # Alias for views that referenced related_stage_id (was Many2one hr.job)
    related_genealogy = fields.Selection(
        GENEALOGY_LEVELS,
        string="Genealogy Status",
        related="genealogy",
        store=False,
    )
    previous_genealogy = fields.Selection(
        GENEALOGY_LEVELS,
        string="Previous Genealogy",
        tracking=True,
    )

    # ── Sales-force codes ─────────────────────────────────────────────────────
    sales_force_code = fields.Char("Sales Force Code", tracking=True)
    recruiter_sales_force_code = fields.Char(
        related="recruiter_id.sales_force_code",
        string="Recruiter Sales Force Code",
    )
    manager_sales_force_code = fields.Char(
        related="manager_id.sales_force_code",
        string="Manager Sales Force Code",
    )
    distributor_sales_force_code = fields.Char(
        related="related_distributor_id.sales_force_code",
        string="Distributor Sales Force Code",
    )
    promoter_sales_force_code = fields.Char(
        related="promoter_id.sales_force_code",
        string="Promoted By Sales Force Code",
    )
    demoter_sales_force_code = fields.Char(
        related="demoter_id.sales_force_code",
        string="Demoted By Sales Force Code",
    )

    # ── Recruitment fields ────────────────────────────────────────────────────
    recruiter_source = fields.Selection(
        [("internal", "Internal"), ("external", "External")],
        string="Recruiter Source",
        tracking=True,
    )
    recruitment_type = fields.Selection(
        [("internal", "Internal"), ("external", "External")],
        string="Recruitment Type",
    )
    recruitment_method = fields.Selection(
        [
            ("pay_in_sheet", "Pay-In Sheet"),
            ("website", "Website"),
            ("sms_shortcode", "SMS Shortcode"),
            ("whatsapp", "WhatsApp"),
            ("app", "App"),
            ("contact_center", "Contact Center"),
            ("other", "Other"),
            ("recruiting_link", "Recruiting Link"),
        ],
        string="Recruitment Method",
    )

    # ── Active status ─────────────────────────────────────────────────────────
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
    active_status_reference_date = fields.Date("Active Status Reference Date")
    active = fields.Boolean("Active", default=True, tracking=True)

    # ── Employee type (retained for cron-job compatibility) ───────────────────
    employee_type = fields.Selection(
        [("sales_force", "Sales Force"), ("internal_employee", "Internal Employee")],
        string="Type",
        default="sales_force",
    )

    # ── Promotion / demotion tracking ─────────────────────────────────────────
    promotion_date = fields.Date("Promotion Date", tracking=True)
    promotion_effective_date = fields.Date("Promotion Effective Date", tracking=True)
    promotion_reason = fields.Selection(
        [
            ("promoted", "Fulfilled Promotion Criteria"),
            ("first_sale", "Made First Sale"),
            ("other", "Other"),
        ],
        string="Promotion Reason",
        tracking=True,
    )
    demotion_date = fields.Date("Demotion Date", tracking=True)
    demotion_effective_date = fields.Date("Demotion Effective Date", tracking=True)
    demotion_reason = fields.Selection(
        [("promoted", "Did Not Fulfill Criteria"), ("other", "Other")],
        string="Demotion Reason",
        tracking=True,
    )
    blacklisted_date = fields.Date("Blacklisted Date", tracking=True)
    unblacklist_date = fields.Date("Un-Blacklisted Date", tracking=True)
    suspended_date = fields.Date("Suspended Date", tracking=True)
    unsuspended_date = fields.Date("Un-Suspended Date", tracking=True)
    move_date = fields.Date("Last Move Date", tracking=True)
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
        tracking=True,
    )

    # ── Contact info ──────────────────────────────────────────────────────────
    contact_info_ids = fields.One2many(
        "hr.contacts", "employee_id", string="Contact Info", tracking=True
    )
    last_contact_date = fields.Date("Last Contact Date", tracking=True)

    # ── Sales tracking ────────────────────────────────────────────────────────
    last_sale_date = fields.Date("Last Sale Date", tracking=True)
    last_sale_date2 = fields.Date("Last Sale Date 2")
    first_sale_date = fields.Date("First Sale Date", tracking=True)
    most_recent_months_sales = fields.Float("Most Recent Months Sales", tracking=True)
    months_since_last_sale = fields.Integer("Months Since Last Sale", tracking=True)
    sold_previous_month = fields.Boolean("Sold Previous Month", tracking=True)
    cumulative4 = fields.Integer("Cumulative 4", tracking=True)
    cumulative5 = fields.Integer("Cumulative 5", tracking=True)
    cumulative6 = fields.Integer("Cumulative 6", tracking=True)
    four_months_sales = fields.Float("Four Months Sales")
    months_since_start = fields.Integer("Months Since Start", tracking=True)

    # ── Status dates ──────────────────────────────────────────────────────────
    potential_recruit_date = fields.Date("Potential Recruitment Date")
    potential_consultant_date = fields.Date("Potential Consultant Date")
    recruit_date = fields.Date("Recruit Date")
    onboard_date = fields.Date("Onboard Date")
    distributor_start_date = fields.Date("Distributor Start Date")
    manager_start_date = fields.Date("Manager Start Date")

    # ── Boolean flags ─────────────────────────────────────────────────────────
    sales_force = fields.Boolean("Is Sales Force?", default=True)
    sale = fields.Boolean("Sale")
    is_manager = fields.Boolean("Is a Manager")
    is_credit_check = fields.Boolean("Is Credit Check Consent")
    is_customer = fields.Boolean("Is Customer")
    is_potential_flag = fields.Boolean("Is Potential")
    credit_score_bus = fields.Boolean("Credit Score Bus")
    active1 = fields.Boolean("Active 1")
    active3 = fields.Boolean("Active 3")
    active6 = fields.Boolean("Active 6")
    inactive = fields.Boolean("Inactive")

    # ── Misc ──────────────────────────────────────────────────────────────────
    language = fields.Many2one("res.lang", "Language")
    manager_blacklist = fields.Char(string="Manager Blacklist")

    # ── Linked records ────────────────────────────────────────────────────────
    linked_consultant_ids = fields.One2many(
        "sf.member", "parent_id", string="Linked Consultants"
    )
    linked_recruit_ids = fields.One2many(
        "sf.member", "recruiter_id", string="Linked Recruits"
    )
    linked_lead_ids = fields.One2many(
        "sf.recruit", "recruiter_id", string="Linked Leads"
    )
    recruit_count = fields.Integer(
        compute="_compute_recruit_count", string="Recruit Count"
    )

    # ── Previous sales data (HTML report) ────────────────────────────────────
    previous_sales_data_html = fields.Html(
        string="Previous Sales Data (HTML)",
        compute="_compute_previous_sales_data_html",
        store=False,
    )

    # ── App login ─────────────────────────────────────────────────────────────
    last_app_login_date = fields.Datetime(
        string="Last App Login Date",
        help="Date and time of the last successful app login via OTP",
        readonly=True,
    )
    days_since_last_login = fields.Integer(
        string="Days Since Last Login",
        compute="_compute_days_since_last_login",
        help="Number of days since last app login",
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends("genealogy")
    def _compute_job_name(self):
        """Compute human-readable genealogy label for backward-compat views."""
        selection_dict = dict(GENEALOGY_LEVELS)
        for rec in self:
            rec.job_name = selection_dict.get(rec.genealogy, rec.genealogy or "")

    @api.depends("last_app_login_date")
    def _compute_days_since_last_login(self):
        for sf_member in self:
            if sf_member.last_app_login_date:
                delta = datetime.now() - sf_member.last_app_login_date
                sf_member.days_since_last_login = delta.days
            else:
                sf_member.days_since_last_login = -1  # Never logged in

    @api.depends(
        "genealogy",
        "related_distributor_id",
        "partner_id.distribution_id",
        "manager_id.related_distributor_id",
        "related_distributor_id.distribution_id",
    )
    def compute_distribution_id(self):
        for record in self:
            if (
                record.genealogy == "Distributor"
                and record.partner_id.distribution_id
            ):
                record.distribution_id = record.partner_id.distribution_id.id
            elif (
                record.related_distributor_id
                and record.related_distributor_id.distribution_id
            ):
                record.distribution_id = (
                    record.related_distributor_id.distribution_id.id
                )
            else:
                record.distribution_id = False

    @api.onchange("genealogy", "manager_id", "manager_id.related_distributor_id")
    def _compute_related_distributor_id(self):
        _logger.info("_compute_related_distributor_id call")
        for record in self:
            if (
                record.genealogy != "Distributor"
                and record.manager_id
                and record.manager_id.related_distributor_id
            ):
                record.related_distributor_id = (
                    record.manager_id.related_distributor_id.id
                )
                record.distribution_id = (
                    record.manager_id.related_distributor_id.distribution_id.id
                )
            elif record.genealogy == "Distributor":
                record.write(
                    {
                        "related_distributor_id": record.id,
                        "distribution_id": record.distribution_id.id,
                    }
                )
            else:
                record.write({"related_distributor_id": False})

    @api.depends("linked_recruit_ids", "linked_lead_ids")
    def _compute_recruit_count(self):
        for rec in self:
            pending_lead_ids = [
                lead.id
                for lead in self.env["sf.recruit"].browse(self.linked_lead_ids.ids)
                if not lead.member_id
            ]
            rec.recruit_count = len(pending_lead_ids) + len(rec.linked_recruit_ids)

    def _compute_previous_sales_data_html(self):
        previous_sales_data_list = self.fetch_previous_sales_data(self.id)

        html_header = """
            <div class="o_account_reports_page o_account_reports_no_print outer_table_container" style="overflow-x: auto; display: block; white-space: nowrap; padding-bottom: 10px; position: relative;">
                <div class="table-responsive table-container" style="overflow-x: auto; display: block; white-space: nowrap; padding-bottom: 10px;">
                    <table style="display: block; overflow-x: auto; white-space: nowrap; padding-bottom: 10px; scrollbar-width: thin; scrollbar-color: #888 #f1f1f1;">
                        <thead>
                            <tr style="border: 1px solid black;">
                                <th style="padding: 10px;">Period</th>
                                <th style="padding: 10px;">BB Sales</th>
                                <th style="padding: 10px;">BB Returns</th>
                                <th style="padding: 10px;">BB Total</th>
                                <th style="padding: 10px;">Puer Sales</th>
                                <th style="padding: 10px;">Puer Returns</th>
                                <th style="padding: 10px;">Puer Totals</th>
                                <th style="padding: 10px;">Sales Totals</th>
                                <th style="padding: 10px;">Consultant Code</th>
                                <th style="padding: 10px;">Consultant Name</th>
                                <th style="padding: 10px;">Manager Code</th>
                                <th style="padding: 10px;">Manager Name</th>
                                <th style="padding: 10px;">Distributor Code</th>
                                <th style="padding: 10px;">Distributor Name</th>
                                <th style="padding: 10px;">Capture Date</th>
                            </tr>
                        </thead>
                        <tbody>
        """
        html_body = "" + "".join(
            [
                f"""
                <tr style="border: 1px solid black; padding: 10px;">
                    <td style="display:none;">{s['id']}</td>
                    <td style="padding: 10px;">{s['period']}</td>
                    <td style="padding: 10px;">{s['bb_sales']}</td>
                    <td style="padding: 10px;">{s['bb_returns']}</td>
                    <td style="padding: 10px;">{s['bb_brand_total']}</td>
                    <td style="padding: 10px;">{s['puer_sales']}</td>
                    <td style="padding: 10px;">{s['puer_returns']}</td>
                    <td style="padding: 10px;">{s['puer_brand_total']}</td>
                    <td style="padding: 10px;">{s['totalsales']}</td>
                    <td style="padding: 10px;">{s['consultantcode']}</td>
                    <td style="padding: 10px;">{s['consultantname']}</td>
                    <td style="padding: 10px;">{s['managercode']}</td>
                    <td style="padding: 10px;">{s['managername']}</td>
                    <td style="padding: 10px;">{s['distributorcode']}</td>
                    <td style="padding: 10px;">{s['distributorname']}</td>
                    <td style="padding: 10px;">{s['capturedate']}</td>
                </tr>
                """
                for s in previous_sales_data_list
            ]
        )
        html_footer = """
                        </tbody>
                    </table>
                </div>
            </div>
        """
        self.previous_sales_data_html = html_header + html_body + html_footer

    # ─────────────────────────────────────────────────────────────────────────
    # Onchange helpers
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange("department_id")
    def _onchange_department(self):
        if self.genealogy in ["Manager", "Prospective Manager"]:
            self.parent_id = self.related_distributor_id.id
        if self.genealogy in ["Consultant", "Prospective Consultant"]:
            self.parent_id = self.manager_id.id

    @api.onchange("manager_id")
    def _onchange_manager_id(self):
        if self.genealogy in ["Manager", "Prospective Manager"]:
            self.parent_id = self.related_distributor_id.id
        if self.genealogy in ["Consultant", "Prospective Consultant"]:
            self.parent_id = self.manager_id.id

    @api.onchange("genealogy")
    def _set_parent_ids(self):
        for rec in self:
            if rec.genealogy == "Distributor":
                rec.is_manager = True
                rec.parent_id = False

            elif rec.genealogy in ["Manager", "Prospective Distributor"]:
                rec.manager_id = rec.id
                rec.is_manager = True
                rec.parent_id = rec.related_distributor_id.id

            elif rec.genealogy in [
                "Potential Consultant",
                "Consultant",
                "Prospective Manager",
            ]:
                rec.is_manager = False
                rec.parent_id = self.manager_id.id

    @api.onchange("name")
    def on_change_name(self):
        if self.name == "False":
            self.name = False
        if self.name and self.name != "False":
            name_list = self.name.split()
            if len(name_list) > 1:
                self.first_name = " ".join(name_list[:-1])
                self.last_name = name_list[-1]
            else:
                self.first_name = name_list[0]

    @api.onchange("first_name")
    def onchange_first_name(self):
        if self.first_name:
            if not self.validate_name(self.first_name):
                raise ValidationError("First name is not valid")
        if self.last_name:
            self.name = str(self.first_name) + " " + str(self.last_name)
        else:
            self.name = str(self.first_name)

    @api.onchange("last_name")
    def onchange_last_name(self):
        if self.last_name:
            if not self.validate_name(self.last_name):
                raise ValidationError("Last name is not valid")
        if self.first_name:
            self.name = str(self.first_name) + " " + str(self.last_name)
        else:
            self.name = str(self.first_name)

    # ─────────────────────────────────────────────────────────────────────────
    # Validation helpers
    # ─────────────────────────────────────────────────────────────────────────

    def validate_name(self, name):
        if 2 <= len(name) <= 50:
            return bool(re.fullmatch(r"[A-Za-zÀ-ÿ\s'-]+", name))
        return False

    def get_formal_name(self):
        if self.first_name and self.last_name:
            return self.first_name + " " + self.last_name

    @api.constrains("sa_id")
    def check_duplicate_id_number(self):
        if self.sa_id:
            count_no = self.search_count([("sa_id", "=", self.sa_id)])
            if count_no > 1:
                raise ValidationError(_("Duplicate ID Number not permitted"))

    @api.constrains("nationality")
    def check_duplicate_nationality(self):
        if self.nationality and self.passport:
            count_no = self.search_count(
                [
                    ("nationality", "=", self.nationality.id),
                    ("passport", "=", self.passport),
                ]
            )
            if count_no > 1:
                raise ValidationError(_("Duplicate Passport Number not permitted"))

    @api.depends("birth_date")
    def _compute_age(self):
        for rec in self:
            rec.age = 0
            if rec.birth_date:
                import datetime as dt
                dob = dt.datetime.strptime(str(rec.birth_date), "%Y-%m-%d").date()
                rec.age = relativedelta(fields.Datetime.now().date(), dob).years

    @api.constrains("email")
    def validate_mail(self):
        if self.email:
            match = re.match(
                r"^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$",
                self.email,
            )
            if match is None:
                raise ValidationError("Not a valid E-mail address")

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        # Default mobile_2 to mobile if not provided
        if not vals.get("mobile_2"):
            vals["mobile_2"] = vals.get("mobile")

        # Compose name from first_name / last_name
        if not vals.get("name"):
            if vals.get("first_name") and vals.get("last_name"):
                vals["name"] = vals["first_name"] + " " + vals["last_name"]
            elif vals.get("mobile"):
                vals["name"] = vals["mobile"]

        # Generate sales_force_code if not supplied
        if not vals.get("sales_force_code"):
            sequence = self.env["ir.sequence"].next_by_code(
                "sales.force.code.sequence"
            )
            vals["sales_force_code"] = sequence

        if vals.get("manager_id"):
            vals["parent_id"] = vals.get("manager_id")

        # Parse RSA ID number
        if vals.get("sa_id"):
            vals = self._parse_sa_id(vals)

        res = super(SfMember, self).create(vals)

        # Create partner if delegation did not auto-create one
        if not res.partner_id:
            _logger.info("sf.member: no partner_id after create — creating partner")
            new_partner_id = self.env["res.partner"].create(
                {
                    "is_company": False,
                    "name": res.name,
                    "email": res.email,
                    "mobile": res.mobile,
                    "sa_id": res.sa_id,
                    "passport": res.passport,
                    "last_name": res.last_name,
                    "first_name": res.first_name,
                    "known_name": res.known_name,
                    "mobile_2": res.mobile_2,
                }
            )
            res.partner_id = new_partner_id.id

        if res.known_name == res.mobile and res.name != res.mobile:
            res.known_name = res.name

        # Set parent hierarchy based on genealogy
        if res.manager_id:
            if res.genealogy in ["Manager", "Prospective Manager"]:
                if res.parent_id.id != res.related_distributor_id.id:
                    res.parent_id = res.related_distributor_id.id
            if res.genealogy in ["Consultant", "Prospective Consultant"]:
                if res.parent_id.id != res.manager_id.id:
                    res.parent_id = res.manager_id.id
        else:
            if res.parent_id:
                res.parent_id = False

        return res

    def write(self, vals):
        res = super(SfMember, self).write(vals)

        # Outbound sync — only for mapped fields that changed
        if res and not self.env.context.get("source_sync", False):
            mapped_fields = self.env["sf.mapping.field"].search(
                [("local_model_name", "=", self._name), ("outbound", "=", True)]
            )

            sync_vals = {}
            for field in mapped_fields:
                if field.local_field_name in vals:
                    if field.local_field_name == "active_status" and vals.get(
                        field.local_field_name
                    ):
                        active_status_dict = dict(
                            self._fields["active_status"].selection
                        )
                        active_status_value = active_status_dict.get(
                            vals.get(field.local_field_name)
                        )
                        if active_status_value:
                            active_status_value = (
                                "Blacklisted"
                                if active_status_value == "Internally Blacklisted"
                                else active_status_value
                            )
                            sync_vals["active_status_bbb"] = active_status_value
                    elif field.local_field_name == "genealogy" and vals.get(
                        field.local_field_name
                    ):
                        # genealogy is now a Selection — send the value directly
                        sync_vals["job_name"] = vals.get(field.local_field_name)
                    else:
                        sync_vals[field.local_field_name] = vals.get(
                            field.local_field_name
                        )

            if "distribution_id" in sync_vals and self.genealogy != "Distributor":
                del sync_vals["distribution_id"]

            _logger.info(
                f"Write Values: {vals} | Mapped: {mapped_fields} | Sync: {sync_vals}"
            )

            if sync_vals:
                if self.partner_id.remote_id and self.remote_id:
                    self.sync_outbound("sf_member", self.id, "update", sync_vals)
                    self.write({"last_outbound_sync_date": datetime.now()})

        # Sync address changes to partner
        address_fields = ["street", "street2", "suburb", "city", "state_id", "country_id"]
        if any(f in vals for f in address_fields):
            for record in self:
                if (
                    record.partner_id
                    and vals.get("street", record.street)
                    and vals.get("city", record.city)
                    and vals.get("country_id", record.country_id.id)
                ):
                    record.partner_id.write(
                        {
                            "street": vals.get("street", record.street),
                            "street2": vals.get("street2", record.street2),
                            "suburb": vals.get("suburb", record.suburb),
                            "city": vals.get("city", record.city),
                            "state_id": vals.get("state_id", record.state_id.id),
                            "country_id": vals.get(
                                "country_id", record.country_id.id
                            ),
                            "zip": vals.get("zip", record.zip),
                        }
                    )
                    record.partner_id.geo_localize()

        return res

    def unlink(self):
        delete_ids = [rec.id for rec in self]
        res = super(SfMember, self).unlink()
        for record_id in delete_ids:
            self.sync_outbound("sf_member", record_id, method="delete")
        return res

    # ─────────────────────────────────────────────────────────────────────────
    # Name search / display
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def name_search(self, name="", args=[], operator="ilike", limit=100):
        if not args:
            args = []
        args.extend(
            [
                "|",
                "|",
                ("name", operator, name),
                ("sales_force_code", operator, name),
                ("known_name", operator, name),
            ]
        )
        records = self.search(args, limit=limit)
        return [(record.id, record.display_name) for record in records.sudo()]

    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get("code_only"):
            for record in self:
                record.display_name = f"{record.id} {record.sales_force_code}"

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────

    def action_view_recruits(self, recruits=False):
        """Open a partner list showing all recruits (linked sf.recruit leads
        that have no member yet, plus sf.member records recruited by this member)."""
        if not recruits:
            recruit_partner_ids = [
                recruit.partner_id.id
                for recruit in self.env["sf.member"].browse(
                    self.linked_recruit_ids.ids
                )
            ]
            lead_partner_ids = [
                lead.partner_id.id
                for lead in self.env["sf.recruit"].browse(self.linked_lead_ids.ids)
                if not lead.member_id
            ]

        tree_view_id = self.env.ref(
            "sales_force_support.res_partner_customer_tree_check"
        ).id
        form_view_id = self.env.ref(
            "sales_force_support.res_partner_customer_view"
        ).id

        domain = [
            "|",
            ("id", "in", recruit_partner_ids),
            ("id", "in", lead_partner_ids),
        ]

        return {
            "type": "ir.actions.act_window",
            "views": [(tree_view_id, "tree"), (form_view_id, "form")],
            "view_mode": "tree,form",
            "view_id": tree_view_id,
            "name": _("Recruits Count"),
            "res_model": "res.partner",
            "domain": domain,
        }

    def button_compuscan_checkscore(self):
        _logger.info("button_compuscan_checkscore.sf_member")
        res = self.partner_id.button_compuscan_checkscore()
        try:
            if int(self.partner_id.compuscan_checkscore_nlr) <= 500:
                colour = "BLUE"
            elif int(self.partner_id.compuscan_checkscore_nlr) <= 618:
                colour = "RED"
            elif int(self.partner_id.compuscan_checkscore_nlr) <= 632:
                colour = "ORANGE"
            else:
                colour = "GREEN"
        except ValueError:
            colour = "BLUE"
        self.write({"credit_score": colour})
        return res

    def get_recent_otp_attempts(self):
        """Get recent OTP attempts for this member."""
        return self.env["user.otp"].search(
            [("sales_force_member_id", "=", self.id)],
            limit=10,
            order="create_date desc",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Kanban view filtering (mirrors hr.employee get_views pattern)
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def get_views(self, views, options=None):
        result = super().get_views(views, options)
        # TODO Phase 7: update action XML IDs from bbb_sales_force_genealogy.* → sales_force_support.*
        actions_dict = {
            "sales_force_support.action_move_consultants": [
                "bbb_sales_force_genealogy_active_prospective_managers",
                "bbb_sales_force_genealogy_active_consultants",
                "bbb_sales_force_genealogy_inactive_prospective_managers",
                "bbb_sales_force_genealogy_inactive_consultants",
                "bbb_sales_force_genealogy_potential_consultants",
            ],
            "sales_force_support.action_move_managers": [
                "bbb_sales_force_genealogy_active_prospective_distributors",
                "bbb_sales_force_genealogy_active_managers",
                "bbb_sales_force_genealogy_inactive_prospective_distributors",
                "bbb_sales_force_genealogy_inactive_managers",
            ],
            "sales_force_support.action_promote_potential_consultants": [
                "bbb_sales_force_genealogy_potential_consultants",
            ],
            "sales_force_support.action_promote_consultants": [
                "bbb_sales_force_genealogy_active_consultants",
            ],
            "sales_force_support.action_promote_prospective_managers": [
                "bbb_sales_force_genealogy_active_prospective_managers",
            ],
            "sales_force_support.action_promote_managers": [
                "bbb_sales_force_genealogy_active_managers",
            ],
            "sales_force_support.action_promote_prospective_distributors": [
                "bbb_sales_force_genealogy_active_prospective_distributors",
            ],
            "sales_force_support.action_demote_managers": [
                "bbb_sales_force_genealogy_active_managers",
                "bbb_sales_force_genealogy_inactive_managers",
            ],
            "sales_force_support.action_demote_distributors": [
                "bbb_sales_force_genealogy_active_distributors",
                "bbb_sales_force_genealogy_inactive_distributors",
            ],
            "sales_force_support.action_suspend_consultants": [
                "bbb_sales_force_genealogy_active_prospective_managers",
                "bbb_sales_force_genealogy_active_consultants",
                "bbb_sales_force_genealogy_inactive_prospective_managers",
                "bbb_sales_force_genealogy_inactive_consultants",
            ],
            "sales_force_support.action_suspend_managers": [
                "bbb_sales_force_genealogy_active_prospective_distributors",
                "bbb_sales_force_genealogy_active_managers",
                "bbb_sales_force_genealogy_inactive_prospective_distributors",
                "bbb_sales_force_genealogy_inactive_managers",
            ],
            "sales_force_support.action_suspend_distributors": [
                "bbb_sales_force_genealogy_active_distributors",
                "bbb_sales_force_genealogy_inactive_distributors",
            ],
            "sales_force_support.action_blacklist_consultants": [
                "bbb_sales_force_genealogy_active_prospective_managers",
                "bbb_sales_force_genealogy_active_consultants",
                "bbb_sales_force_genealogy_inactive_prospective_managers",
                "bbb_sales_force_genealogy_inactive_consultants",
            ],
            "sales_force_support.action_blacklist_managers": [
                "bbb_sales_force_genealogy_active_prospective_distributors",
                "bbb_sales_force_genealogy_active_managers",
                "bbb_sales_force_genealogy_inactive_prospective_distributors",
                "bbb_sales_force_genealogy_inactive_managers",
            ],
            "sales_force_support.action_blacklist_distributors": [
                "bbb_sales_force_genealogy_active_distributors",
                "bbb_sales_force_genealogy_inactive_distributors",
            ],
        }
        if options and options.get("toolbar"):
            list_view = result["views"].get("list")
            if (
                list_view
                and list_view.get("toolbar")
                and list_view["toolbar"].get("action")
            ):
                view_list_name = (
                    self.env["ir.ui.view"]
                    .sudo()
                    .browse(result["views"]["list"]["id"])
                    .name
                )
                delete_actions = []
                for action in list_view["toolbar"]["action"]:
                    action_id = action.get("id")
                    xml_id = (
                        self.env["ir.actions.act_window"]
                        .sudo()
                        .browse(action_id)
                        .xml_id
                    )
                    if xml_id:
                        if not (view_list_name in actions_dict.get(xml_id, [])):
                            delete_actions.append(action)
                for act in delete_actions:
                    list_view["toolbar"]["action"].remove(act)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Geographic allocation
    # ─────────────────────────────────────────────────────────────────────────

    def _get_nearby(self, domain=None, distance=None, order=None, limit=None):
        self.ensure_one()
        partner = self.partner_id
        values = [
            partner.partner_latitude,
            partner.partner_latitude,
            partner.partner_longitude,
        ]

        # NOTE: Raw SQL uses sf_member table (was hr_employee)
        query = """SELECT *,
            h.distance AS distance
            FROM (SELECT sf_member.*, p.id as partner_id,
                acos(sin(p.partner_latitude * pi() / 180) * sin(%s * pi() / 180)
                + cos(p.partner_latitude * pi() / 180) * cos(%s * pi() / 180) *
                cos((%s * pi() / 180) - (p.partner_longitude * pi() / 180))
                ) * 6371 AS distance
            FROM sf_member JOIN res_partner p ON p.id = sf_member.partner_id"""

        if domain:
            query += " WHERE"
            if domain:
                table, sql, params = (
                    self.env["sf.member"]._where_calc(domain).get_sql()
                )
                sql = sql.replace('"sf_member__partner_id"', "p")
                query += " " + sql
                values.extend(params)
                query += ") h"

        if distance:
            values.append(distance)
            query += " WHERE h.distance <= %s"

        if order:
            query += " ORDER BY %s" % order

        if limit:
            values.append(limit)
            query += " LIMIT %s"

        self.env.cr.execute(query, values)
        id_distances = self.env.cr.fetchmany(100)
        while id_distances:
            for res_id, distance in id_distances:
                yield self.browse([res_id]), distance
            id_distances = self.env.cr.fetchmany(100)

    def button_allocate_manager(self):
        for employee in self:
            partner = employee.partner_id
            partner.write(
                {
                    "street": employee.street,
                    "zip": employee.zip,
                    "city": employee.city,
                    "state_id": employee.state_id.id,
                    "country_id": employee.country_id.id,
                }
            )
            partner.geo_localize()

        for employee in self:
            if employee.recruiter_id and not employee.manager_id:
                if employee.recruiter_id.genealogy in (
                    "Manager",
                    "Prospective Distributor",
                    "Distributor",
                ):
                    employee.manager_id = employee.recruiter_id
                else:
                    employee.manager_id = employee.recruiter_id.manager_id
                return

            domain = [("genealogy", "in", ("Manager", "Prospective Distributor"))]

            if employee.manager_id and employee.manager_blacklist:
                self.manager_blacklist += ",%s" % employee.manager_id.id
            elif employee.manager_id:
                self.manager_blacklist = str(employee.manager_id.id)

            if self.manager_blacklist:
                domain.append(
                    ("id", "not in", self.manager_blacklist.split(","))
                )

            if employee.state_id:
                state_domain_term = ("state_id", "=", employee.state_id.id)
                domain.append(state_domain_term)

            if employee.country_id:
                country_domain_term = ("country_id", "=", employee.country_id.id)
                domain.append(country_domain_term)
            else:
                raise UserError(_("Consultant address is not set"))

            order = "h.four_months_sales DESC, distance"

            if (
                employee.partner_id.partner_longitude
                and employee.partner_id.partner_latitude
            ):
                distance = 1.0
                lon_min = (
                    "partner_id.partner_longitude",
                    ">=",
                    employee.partner_id.partner_longitude - distance,
                )
                lon_max = (
                    "partner_id.partner_longitude",
                    "<=",
                    employee.partner_id.partner_longitude + distance,
                )
                lat_min = (
                    "partner_id.partner_latitude",
                    ">=",
                    employee.partner_id.partner_latitude - distance,
                )
                lat_max = (
                    "partner_id.partner_latitude",
                    "<=",
                    employee.partner_id.partner_latitude + distance,
                )
                domain.extend([lon_min, lon_max, lat_min, lat_max])
                employees = [
                    p.id
                    for p, d in self._get_nearby(domain, distance, order=order)
                ]
                domain = [
                    t
                    for t in domain
                    if t not in [lon_min, lon_max, lat_min, lat_max]
                ]
            else:
                employees = False

            order = "four_months_sales DESC"

            if not employees and employee.city:
                city_domain_term = ("city", "=", employee.city)
                domain.append(city_domain_term)
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(city_domain_term)

            if not employees and employee.state_id:
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(state_domain_term)

            if not employees:
                employees = self.env["sf.member"].search(domain, order=order)

            if employees:
                if isinstance(employees[0], int):
                    employee.manager_id = employees[0]
                    employee.recruiter_id = employees[0]
                    employee.consultant_id = employees[0]
                else:
                    employee.manager_id = employees[0][0]
                    employee.recruiter_id = employees[0][0]
                    employee.consultant_id = employees[0][0]
            else:
                raise UserError(_("Could not find a manager nearby"))

    # ─────────────────────────────────────────────────────────────────────────
    # Remote synchronisation helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get_selection_labels(self, fields_to_sync):
        """Map selection field values to their labels for sync."""
        selection_fields = {"active_status": "active_status"}
        result = {}
        for field, value in fields_to_sync.items():
            if field in selection_fields:
                field_options = self.fields_get([field])[field]["selection"]
                label = dict(field_options).get(value, value)
                result[field] = label
            else:
                result[field] = value
        return result

    def get_many2one_names(self, fields_to_sync):
        """Map Many2one field values to their display names for sync."""
        field_record_models = {
            "country_id": ["res.country", "name", "country_name"],
            "state_id": ["res.country.state", "name", "state_name"],
            "genealogy": None,  # Selection — handle directly
            "manager_id": ["sf.member", "sales_force_code", "manager_sales_force_code"],
            "related_distributor_id": [
                "sf.member",
                "sales_force_code",
                "distributor_sales_force_code",
            ],
        }
        result = {}
        for field, value in fields_to_sync.items():
            if field in field_record_models:
                model_info = field_record_models[field]
                if model_info is None:
                    # genealogy is a Selection — the value IS the label
                    result["job_name"] = value
                else:
                    field_record = self.env[model_info[0]].browse([value])
                    if field_record:
                        label = getattr(field_record, model_info[1])
                        result[model_info[2]] = label
            else:
                result[field] = value
        return result

    def create_in_remote_db(self, sf_records):
        if not sf_records:
            _logger.info("No SFM records to sync")
            return

        he_mapped_fields = self.env["sf.mapping.field"].search(
            [("local_model_name", "=", "sf.member"), ("outbound", "=", True)]
        )
        rp_mapped_fields = self.env["sf.mapping.field"].search(
            [("local_model_name", "=", "res.partner"), ("outbound", "=", True)]
        )

        active_status_dict = dict(
            self.env["sf.member"]._fields["active_status"].selection
        )

        he_mapped_field_ids = [x.local_field_id.id for x in he_mapped_fields]
        he_many2one_fields = self.env["ir.model.fields"].search(
            [("id", "in", he_mapped_field_ids), ("ttype", "=", "many2one")]
        )
        he_many2one_field_names = [field.name for field in he_many2one_fields]

        rp_mapped_field_ids = [x.local_field_id.id for x in rp_mapped_fields]
        rp_many2one_fields = self.env["ir.model.fields"].search(
            [("id", "in", rp_mapped_field_ids), ("ttype", "=", "many2one")]
        )
        rp_many2one_field_names = [field.name for field in rp_many2one_fields]

        for record in sf_records:
            he_sync_vals = {}
            for field in he_mapped_fields:
                field_name = field.local_field_name
                if field_name == "active_status" and record.active_status:
                    av = active_status_dict.get(record.active_status)
                    if av:
                        av = "Blacklisted" if av == "Internally Blacklisted" else av
                        he_sync_vals["active_status_bbb"] = av
                elif field_name == "genealogy" and record.genealogy:
                    he_sync_vals["job_name"] = record.genealogy
                else:
                    if field_name in he_many2one_field_names:
                        he_sync_vals[field_name] = (
                            record[field_name].id if record[field_name] else False
                        )
                    else:
                        he_sync_vals[field_name] = record[field_name]

            rp_sync_vals = {}
            for field in rp_mapped_fields:
                field_name = field.local_field_name
                if field_name in rp_many2one_field_names:
                    rp_sync_vals[field_name] = (
                        record[field_name].id if record[field_name] else False
                    )
                else:
                    rp_sync_vals[field_name] = record[field_name]

            if rp_sync_vals and he_sync_vals:
                if not record.partner_id.remote_id:
                    record.partner_id.sync_outbound(
                        "res_partner",
                        record.partner_id.id,
                        method="create",
                        sync_vals=rp_sync_vals,
                    )
                if record.partner_id.remote_id:
                    record.sync_outbound(
                        "sf_member", record.id, method="create", sync_vals=he_sync_vals
                    )
                if not record.partner_id.remote_id or not record.remote_id:
                    _logger.error(
                        f"Failed to sync SFM | id: {record.id}, code: {record.sales_force_code}"
                    )
                else:
                    _logger.info(
                        f"Synced SFM | id: {record.id}, code: {record.sales_force_code}"
                    )

    def sync_outbound(self, model_name, record_id, method="update", sync_vals={}):
        ir_config = self.env["ir.config_parameter"]
        # NOTE: config param keys updated from bbb_sales_force_genealogy.* to
        # sales_force_support.* — migration script must copy old param values.
        sync_enabled = ir_config.get_param(
            "sales_force_support.enable_outbound_synchronisation", default=False
        )
        if not sync_enabled:
            _logger.warning("Outbound synchronisation is disabled")
            return

        sync_url = ir_config.get_param(
            "sales_force_support.outbound_url", default=False
        )
        outbound_database = ir_config.get_param(
            "sales_force_support.outbound_database", default=False
        )
        outbound_login = ir_config.get_param(
            "sales_force_support.outbound_login", default=False
        )
        outbound_password = ir_config.get_param(
            "sales_force_support.outbound_password", default=False
        )

        if not all([sync_url, outbound_database, outbound_login, outbound_password]):
            _logger.warning("Outbound synchronisation not fully configured")
            return

        headers = {
            "content-type": "application/json",
            "User-Agent": "Asuer Odoo",
            "Connection": "keep-alive",
            "Accept": "*/*",
            "AcceptEncoding": "gzip, deflate, br",
        }

        auth_endpoint = f"{sync_url}/web/session/authenticate"
        payload = {
            "jsonrpc": "2.0",
            "params": {
                "db": outbound_database,
                "login": outbound_login,
                "password": outbound_password,
            },
        }

        try:
            response = requests.post(
                url=auth_endpoint, data=json.dumps(payload), headers=headers
            )
            response.raise_for_status()
            session_id = response.cookies.get("session_id")

            if session_id:
                headers["X-Openerp"] = f"session_id={session_id}"
                headers["Cookie"] = f"session_id={session_id}"
                sync_vals["id"] = record_id
                payload = {"jsonrpc": "2.0", "params": sync_vals}

                try:
                    if method == "create":
                        sync_endpoint = f"{sync_url}/sales_force/{model_name}"
                        response = requests.post(
                            url=sync_endpoint,
                            data=json.dumps(payload),
                            headers=headers,
                        )
                        response.raise_for_status()
                        if (
                            response.json().get("result")
                            and response.json().get("result").get("id")
                        ):
                            remote_id = response.json().get("result").get("id")
                            self.browse([record_id]).write({"remote_id": remote_id})
                    elif method == "update":
                        sync_endpoint = (
                            f"{sync_url}/sales_force/{model_name}/{self.id}"
                        )
                        response = requests.post(
                            url=sync_endpoint,
                            data=json.dumps(payload),
                            headers=headers,
                        )
                        response.raise_for_status()
                except Exception as e:
                    _logger.error(f"Sync failed: {str(e)}")
            else:
                _logger.error("Failed to retrieve session ID")
        except Exception:
            _logger.error("Sync outbound request failed")

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_sa_id(self, vals):
        """Parse South African ID number and populate birth_date, gender."""
        import datetime as dt
        number = vals.get("sa_id")
        valid = True
        if len(number) != 13:
            valid = False
        try:
            int(number)
        except ValueError:
            valid = False
        if not valid:
            raise UserError(_("Invalid RSA Number!"))
        current_year = dt.datetime.now().year % 100
        prefix = "19"
        if current_year > int(number[0:2]):
            prefix = "20"
        year = int(prefix + number[0:2])
        month = int(number[2:4])
        day = int(number[4:6])
        gender = int(number[6:10])
        if month <= 0 or month > 12 or day <= 0 or day > 31:
            raise UserError(_("Invalid RSA Number!"))
        if month < 10:
            month = "0%s" % month
        if day < 10:
            day = "0%s" % day
        try:
            vals["birth_date"] = "%s-%s-%s" % (year, month, day)
            vals["gender"] = "female" if gender <= 4999 else "male"
        except Exception:
            raise UserError(_("Invalid RSA Number!"))
        return vals

    def fetch_previous_sales_data(self, member_id):
        # NOTE: Raw SQL updated — hr_employee → sf_member
        sql_query = """
            SELECT bps.id as ID, bps."period" as Period,
            coalesce(bpsl.bb_sales, 0) as bb_sales,
            coalesce(bpsl.bb_returns, 0) as bb_returns,
            coalesce(bpsl.bb_brand_total, 0) as bb_brand_total,
            coalesce(bpsl.puer_sales, 0) as puer_sales,
            coalesce(bpsl.puer_returns, 0) as puer_returns,
            coalesce(bpsl.puer_brand_total, 0) as puer_brand_total,
            coalesce(bpsl.bb_brand_total, 0) + coalesce(bpsl.puer_brand_total, 0) as TotalSales,
            he.sales_force_code as ConsultantCode, he.name as ConsultantName,
            he2.sales_force_code as ManagerCode, he2."name" as ManagerName,
            he3.sales_force_code as DistributorCode, rp."name" as DistributorName,
            bps.capture_start_date as CaptureDate
            FROM bb_payin_sheet_line bpsl
            LEFT JOIN bb_payin_sheet bps ON bps.id = bpsl.payin_sheet_id
            LEFT JOIN sf_member he ON he.id = bpsl.consultant_id
            LEFT JOIN sf_member he2 ON he2.id = bps.manager_id
            LEFT JOIN sf_member he3 ON he3.id = bps.distributor_id
            LEFT JOIN res_partner rp ON rp.id = he3.partner_id
            WHERE he.id = %s AND bps.state in ('verified')
            ORDER BY bps."date" DESC
        """
        self.env.cr.execute(sql_query, (member_id,))
        result_set = self.env.cr.fetchall()
        previous_sales_data_list = []
        for result in result_set:
            previous_sales_data_list.append(
                {
                    "id": result[0],
                    "period": result[1],
                    "bb_sales": result[2],
                    "bb_returns": result[3],
                    "bb_brand_total": result[4],
                    "puer_sales": result[5],
                    "puer_returns": result[6],
                    "puer_brand_total": result[7],
                    "totalsales": result[8],
                    "consultantcode": result[9],
                    "consultantname": result[10],
                    "managercode": result[11],
                    "managername": result[12],
                    "distributorcode": result[13],
                    "distributorname": result[14],
                    "capturedate": result[15],
                }
            )
        return previous_sales_data_list

    # ─────────────────────────────────────────────────────────────────────────
    # Pay-In Sheet integration  (source: bb_payin/models/hr_employee.py)
    #   • hr.employee  → sf.member
    #   • job_id.name  → genealogy  (Selection)
    #   • bb_payin.*   → sales_force_support.*  (action XML IDs)
    # ─────────────────────────────────────────────────────────────────────────

    status_trail_ids = fields.One2many(
        "bb.payin.history", "employee_id", string="Active Status History"
    )
    payin_count = fields.Integer(
        string="Pay-In Sheets Count", compute="_compute_payin_count"
    )
    lines_capture_start_date = fields.Datetime("Lines Timer")
    lines_capture_stop_date = fields.Datetime("Timesheet Timer Last Use")

    def _compute_payin_count(self):
        for rec in self:
            ids = []
            if rec.genealogy in ["Manager", "Prospective Distributor"]:
                ids = (
                    self.env["bb.payin.sheet"].search([("manager_id", "=", rec.id)]).ids
                )
            elif rec.genealogy == "Distributor":
                ids = (
                    self.env["bb.payin.sheet"]
                    .search([("distributor_id", "=", rec.id)])
                    .ids
                )
            else:
                ids = (
                    self.env["bb.payin.sheet.line"]
                    .search([("consultant_id", "=", self.id)])
                    .mapped("payin_sheet_id")
                    .ids
                )
            rec.payin_count = len(ids)

    def get_sheets(self, related_distributor_id):
        return self.env["bb.payin.sheet"].search(
            [
                ("distributor_id", "=", related_distributor_id.id),
                ("state", "=", "captured"),
            ]
        )

    def get_payin_sheets(self):
        ids = []
        if self.genealogy in ["Manager", "Prospective Distributor"]:
            ids = self.env["bb.payin.sheet"].search([("manager_id", "=", self.id)]).ids
        elif self.genealogy == "Distributor":
            ids = (
                self.env["bb.payin.sheet"]
                .search([("distributor_id", "=", self.id)])
                .ids
            )
        else:
            ids = (
                self.env["bb.payin.sheet.line"]
                .search([("consultant_id", "=", self.id)])
                .mapped("payin_sheet_id")
                .ids
            )

        action = self.env["ir.actions.actions"]._for_xml_id(
            "sales_force_support.action_payin_history"
        )
        if len(ids) > 1:
            action["domain"] = [("id", "in", ids)]
        elif len(ids) == 1:
            form_view = [
                (self.env.ref("sales_force_support.payin_form_view").id, "form")
            ]
            if "views" in action:
                action["views"] = form_view + [
                    (state, view)
                    for state, view in action["views"]
                    if view != "form"
                ]
            else:
                action["views"] = form_view
            action["res_id"] = ids[0]
        else:
            action = {"type": "ir.actions.act_window_close"}

        return action

    def update_consultant_sales_activity_info(self, payin_date):
        import math
        for consultant_id in self:
            first_payin = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "<=", payin_date),
                    ("member_id", "=", consultant_id.id),
                    "|",
                    ("personal_bbb_sale", ">", 0),
                    ("personal_puer_sale", ">", 0),
                ],
                order="payin_date asc",
                limit=1,
            )
            payin_history = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "<=", payin_date),
                    ("member_id", "=", consultant_id.id),
                    "|",
                    ("personal_bbb_sale", ">", 0),
                    ("personal_puer_sale", ">", 0),
                ],
                order="payin_date desc",
                limit=3,
            )

            write_cons_vals = {
                "sale": False,
                "first_sale_date": False,
                "last_sale_date": False,
                "sold_previous_month": False,
                "most_recent_months_sales": 0.0,
                "four_months_sales": 0.0,
                "months_since_last_sale": -1,
            }

            if payin_history and len(payin_history) > 0:
                write_cons_vals["sale"] = True

                first_sale_date = first_payin[0].payin_date
                write_cons_vals["first_sale_date"] = first_sale_date

                last_payin_history_date = payin_history[0].payin_date
                write_cons_vals["last_sale_date"] = last_payin_history_date

                if last_payin_history_date == payin_date:
                    write_cons_vals["sold_previous_month"] = True

                last_payin_history_total_personal_sales = payin_history[
                    0
                ].total_personal_sales
                write_cons_vals["most_recent_months_sales"] = (
                    last_payin_history_total_personal_sales
                )

                four_months_sales = sum(
                    [
                        history.total_personal_sales
                        for history in payin_history
                        if not math.isnan(history.total_personal_sales)
                    ]
                )
                write_cons_vals["four_months_sales"] = four_months_sales

                months_since_last_sale = (payin_date.year - payin_date.year) * 12 + (
                    payin_date.month - last_payin_history_date.month
                )
                write_cons_vals["months_since_last_sale"] = months_since_last_sale

                # Promote Potential Consultant → Consultant on first sale
                if consultant_id.genealogy == "Potential Consultant":
                    write_cons_vals["genealogy"] = "Consultant"

            consultant_id.write(write_cons_vals)

    def update_active_status(self, payin_date=False, limit=False):
        import math, datetime as dt
        if not payin_date:
            payins_search = self.env["bb.payin.sheet"].search(
                [("state", "in", ["verified"]), ("payin_date", "!=", False)],
                order="payin_date desc",
                limit=1,
            )
            if payins_search.ids and len(payins_search.ids) > 0:
                payin_date = payins_search[0].payin_date
                payin_date = payin_date.strftime("%Y-%m-%d")
            else:
                return False

        consultants_domain = [
            "|",
            "&",
            ("last_sale_date", "<", payin_date),
            ("last_sale_date", "=", False),
            ("active", "=", True),
        ]
        for record in self.env["sf.member"].search(consultants_domain, limit=limit):
            member_id = record.id
            member_genealogy = record.genealogy
            previous_history_id = self.env["bb.payin.history"].search(
                [
                    ("member_id", "=", member_id),
                    ("payin_date", "!=", False),
                    ("payin_date", "<=", payin_date),
                ],
                order="payin_date desc",
                limit=4,
            )
            if previous_history_id.ids and len(previous_history_id.ids) > 0:
                last_payin_history_date = previous_history_id[0].payin_date
                last_payin_history_bb_sales = previous_history_id[0].personal_bbb_sale
                last_payin_history_puer_sales = previous_history_id[
                    0
                ].personal_puer_sale

                if last_payin_history_bb_sales > 0 or last_payin_history_puer_sales > 0:
                    selected_payin_date = dt.datetime.strptime(
                        payin_date, "%Y-%m-%d"
                    ).date()
                    months_since_last_sale = (
                        selected_payin_date.year - last_payin_history_date.year
                    ) * 12 + (
                        selected_payin_date.month - last_payin_history_date.month
                    )
                    most_recent_months_sales = (
                        last_payin_history_bb_sales + last_payin_history_puer_sales
                    )

                    four_months_sales = sum(
                        [
                            history.total_personal_sales
                            for history in previous_history_id
                            if not math.isnan(history.total_personal_sales)
                        ]
                    )

                    write_cons_vals = {
                        "last_sale_date": last_payin_history_date,
                        "months_since_last_sale": months_since_last_sale,
                        "most_recent_months_sales": most_recent_months_sales,
                        "four_months_sales": four_months_sales,
                    }

                    if months_since_last_sale == 0:
                        write_cons_vals["sold_previous_month"] = True
                    else:
                        write_cons_vals["sold_previous_month"] = False

                    # Promote Potential Consultant → Consultant on first sale
                    if member_genealogy == "Potential Consultant":
                        write_cons_vals["genealogy"] = "Consultant"

                    if not record.sale:
                        write_cons_vals["sale"] = True

                    initial_history_id = self.env["bb.payin.history"].search(
                        [
                            ("member_id", "=", member_id),
                            ("payin_date", "!=", False),
                        ],
                        order="payin_date asc",
                        limit=1,
                    )
                    if (
                        not record.first_sale_date
                        and initial_history_id
                        and len(initial_history_id) > 0
                    ):
                        write_cons_vals["first_sale_date"] = (
                            initial_history_id.payin_date
                        )

                    record.write(write_cons_vals)
