# -*- coding: utf-8 -*-
# NEW standalone model — replaces hr.applicant for the Sales Force recruit pipeline.
# Sources merged:
#   - botle_buhle_custom/models/hr_applicant.py
#   - bbb_sales_force_genealogy/models/hr_applicant.py
#
# Key transformations:
#   - _inherits = {"res.partner": "partner_id"}  (no _inherit from hr.applicant)
#   - stage_id → Many2one("sf.recruit.stage")
#   - emp_id → member_id (Many2one "sf.member")
#   - All Many2one("hr.employee") → Many2one("sf.member")
#   - hr.recruitment.stage → sf.recruit.stage
#   - job_id / hr.job → genealogy Selection field
#   - stage_id.create_employee → stage_id.create_member
#   - stage_id.hired_stage → stage_id.joined_stage
#   - applicant_id → recruit_id in vetting_ids / communications_ids
#   - XML view refs: botle_buhle_custom.* → sales_force_support.*

import time
import math
import re
import logging
import datetime

import phonenumbers

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

# Genealogy levels — canonical list (kept in sync with sf_member.py)
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


class SfRecruit(models.Model):
    _name = "sf.recruit"
    _description = "Sales Force Recruit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _inherits = {"res.partner": "partner_id"}
    _order = "id desc"

    # ── Partner delegation ────────────────────────────────────────────────────
    # Fields on res.partner (name, email, mobile, phone, street, city, state_id,
    # country_id, sa_id, passport, first_name, last_name, known_name, mobile_2,
    # suburb, birth_date, gender, nationality, credit_score, compuscan_*,
    # unverified_*, consumerview_ref, etc.) are inherited via delegation.
    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        string="Partner",
        auto_join=True,
    )

    # ── Stage ─────────────────────────────────────────────────────────────────
    stage_id = fields.Many2one(
        "sf.recruit.stage",
        "Stage",
        ondelete="restrict",
        tracking=True,
        copy=False,
        index=True,
        group_expand="_read_group_stage_ids",
        default=lambda self: self._default_stage_id(),
    )
    stage_name = fields.Char("Stage Name", related="stage_id.name")
    related_stage_id = fields.Many2one(
        "sf.recruit.stage",
        string="Related Stage",
        related="stage_id",
    )
    create_member = fields.Boolean(
        "Create Sales Force Member?",
        related="stage_id.create_member",
    )

    # ── Linked sf.member (set when recruit becomes a member) ─────────────────
    member_id = fields.Many2one(
        "sf.member",
        "Sales Force Member",
        help="Set once the recruit has been onboarded as an sf.member.",
    )

    # ── Hierarchy / Relations (all to sf.member) ──────────────────────────────
    manager_id = fields.Many2one("sf.member", "Manager", tracking=True)
    recruiter_id = fields.Many2one("sf.member", "Recruited By", tracking=True)
    consultant_id = fields.Many2one("sf.member", "Consultant")
    related_distributor_id = fields.Many2one(
        "sf.member",
        "Distributor",
        compute="_compute_related_distributor_id",
        inverse="_set_related_distributor_id",
        store=True,
        tracking=True,
    )
    related_prospective_manager_id = fields.Many2one(
        "sf.member", "Related Prospective Manager", tracking=True
    )
    related_prospective_distributor_id = fields.Many2one(
        "sf.member", "Related Prospective Distributor", tracking=True
    )
    previous_manager_id = fields.Many2one(
        "sf.member", "Previous Manager", tracking=True
    )
    previous_distributor_id = fields.Many2one(
        "sf.member", "Previous Distributor", tracking=True
    )

    # ── Genealogy (replaces job_id / hr.job) ──────────────────────────────────
    genealogy = fields.Selection(
        GENEALOGY_LEVELS,
        string="Genealogy",
        tracking=True,
    )
    job_name = fields.Char(
        "Genealogy",
        compute="_compute_job_name",
        store=True,
    )

    # ── Core flags ────────────────────────────────────────────────────────────
    active = fields.Boolean("Active", default=True, tracking=True)
    sales_force = fields.Boolean(
        "Is Sales Force?",
        default=lambda self: self.get_sale_force(),
    )
    employee_type = fields.Selection(
        [("sales_force", "Sales Force"), ("internal_employee", "Internal Employee")],
        string="Type",
        default=lambda self: self.get_employee_type(),
    )
    employee_created = fields.Boolean("Member Created")
    meeting_set = fields.Boolean("Meeting Created")
    address_verified = fields.Boolean("Address Verified")

    # ── Contact / personal fields on the recruit record itself ────────────────
    image = fields.Binary("Image")
    language = fields.Many2one("res.lang", "Language")
    is_customer = fields.Boolean("Is Customer")
    is_potential_flag = fields.Boolean("Is Potential")

    # ── Sales Force Code ──────────────────────────────────────────────────────
    sales_force_code = fields.Char("Sales Force Code")

    # ── Date tracking ─────────────────────────────────────────────────────────
    onboard_date = fields.Date("Onboard Date")
    distributor_start_date = fields.Date("Distributor Start Date")
    manager_start_date = fields.Date("Manager Start Date")
    last_sale_date = fields.Date("Last Sale Date")
    first_sale_date = fields.Date("First Sale Date")
    last_contact_date = fields.Date("Last Contact Date")
    move_date = fields.Date("Last Move Date", tracking=True)

    # Recruitment stage date tracking
    state_change_date = fields.Datetime("Last Stage Change Date")
    potential_lead_date = fields.Datetime("Potential Lead Date", tracking=True)
    lead_date = fields.Datetime("Lead Date", tracking=True)
    potential_recruit_date = fields.Date("Potential Recruit Date", tracking=True)
    recruit_date = fields.Date("Recruit Date", tracking=True)
    potential_consultant_date = fields.Date(
        "Potential Consultant Date", tracking=True
    )

    # ── Stage ageing ──────────────────────────────────────────────────────────
    days_in_current_recruiting_stage = fields.Integer(
        "Days In Stage", compute="_compute_recruitment_stage_ageing", default=0
    )
    days_in_recruiting_process = fields.Integer(
        "Days In Process", compute="_compute_recruitment_process_ageing", default=0
    )
    stage_not_moved = fields.Boolean("Stage Unchanged")

    # ── Call-centre fields ────────────────────────────────────────────────────
    last_call_date = fields.Date("Last Call Date", tracking=True)
    call_agent = fields.Char("Call Agent", tracking=True)
    call_disposition = fields.Selection(
        [
            ("already_joined", "Already Joined"),
            ("part_of_another_business", "Already part of another Direct Selling Business"),
            ("archived", "Archived"),
            ("attending_meeting", "Attending Meeting"),
            ("complaint", "Complaint"),
            ("do_not_call", "Do not call"),
            ("escalation", "Escalation"),
            ("expired_meeting_no_answer", "Expired Meeting (No Answer)"),
            ("financial_problems", "Financial Problems"),
            ("funeral", "Funeral"),
            ("going_to_event", "Going to Event"),
            ("incorrect_number", "Incorrect Number"),
            ("manager_not_found", "Manager not found"),
            ("need_information", "Need Information"),
            ("no_passport", "No Passport"),
            ("no_credit_check_consent", "No credit check consent"),
            ("not_interested", "Not Interested"),
            ("not_found_in_database", "Not found in the database"),
            ("not_well_sick", "Not well/Sick"),
            ("number_not_found", "Number not found"),
            ("onboarding_completed", "On-boarding Completed"),
            ("partner_attending_meeting", "Partner Attending Meeting"),
            ("partner_not_attending_meeting", "Partner Not Attending Meeting"),
            ("passport_expired", "Passport Expired"),
            ("passport_expired_no_passport", "Passport Expired/No Passport"),
            ("technical_glitch", "Technical Glitch"),
            ("test_inbound", "Test Inbound"),
            ("too_far", "Too Far"),
            ("want_to_buy", "Want to Buy"),
            ("working_on_that_day", "Working on that day"),
            ("not_attending_meeting", "Not Attending Meeting"),
            ("call_back", "Call Back"),
            ("dropped_call", "Dropped Call"),
            ("did_not_answer", "Did not Answer"),
        ],
        string="Disposition",
        tracking=True,
    )
    call_count = fields.Integer("Call Count", default=0)

    # ── Recruitment method fields ─────────────────────────────────────────────
    recruiter_source = fields.Selection(
        [("internal", "Internal"), ("external", "External")],
        string="Recruiter Source",
        tracking=True,
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
    registration_channel = fields.Selection(
        [
            ("registration_form", "Registration Form"),
            ("contact_centre", "Contact Centre"),
            ("manual_capture", "Manual Capture (Pay-In Sheets)"),
        ],
        string="Registration Channel",
    )

    # ── Onboarding progress fields (mobile app / recruiting v2) ──────────────
    mobile_app_id = fields.Integer("Mobile App ID")
    is_interested = fields.Boolean("Is Interested", tracking=True)
    interested_date = fields.Date("Interested Date", tracking=True)
    mobile_confirmed = fields.Boolean("Mobile Confirmed", tracking=True)
    mobile_confirm_date = fields.Date("Mobile Confirmed Date", tracking=True)
    induction_meeting_invited = fields.Boolean(
        "Induction Meeting Invited", tracking=True
    )
    induction_meeting_invite_date = fields.Date(
        "Induction Meeting Invited Date", tracking=True
    )
    induction_meeting_scheduled_date = fields.Date(
        "Induction Meeting Scheduled Date", tracking=True
    )
    induction_meeting_attended = fields.Boolean(
        "Induction Meeting Attended", tracking=True
    )
    induction_meeting_attendance_date = fields.Date(
        "Induction Meeting Attended Date", tracking=True
    )
    documents_submitted = fields.Boolean("Documents Submitted", tracking=True)
    documents_submitted_date = fields.Date(
        "Documents Submitted Date", tracking=True
    )
    onboarding_started = fields.Boolean("Onboarding Started", tracking=True)
    onboarding_start_date = fields.Date("Onboarding Start Date", tracking=True)
    credit_check_permission_granted = fields.Boolean(
        "Vetting Consent Granted", tracking=True
    )
    credit_check_permission_date = fields.Date(
        "Vetting Consent Granted Date", tracking=True
    )
    credit_check_generated = fields.Boolean(
        "Vetting Consent Generated", tracking=True
    )
    credit_check_generated_date = fields.Date(
        "Vetting Consent Generated Date", tracking=True
    )
    consumerview_address_confirmed = fields.Boolean(
        "ConsumerView Address Confirmed", tracking=True
    )
    consumerview_address_confirm_date = fields.Date(
        "ConsumerView Address Confirmed Date", tracking=True
    )
    interview_started = fields.Boolean("Interview Started", tracking=True)
    interview_start_date = fields.Date("Interview Start Date", tracking=True)
    interview_status = fields.Char("Interview Status", tracking=True)
    interview_decline_reasons = fields.Many2many(
        "interview.decline.reasons",
        string="Interview Decline Reasons",
        tracking=True,
    )
    onboarding_completed = fields.Boolean("Onboarding Completed", tracking=True)
    onboarding_complete_date = fields.Date("Onboarding Complete Date", tracking=True)

    # ── Linked vetting / communications ───────────────────────────────────────
    vetting_ids = fields.One2many(
        "res.vetting", "recruit_id", string="Vettings"
    )
    communications_ids = fields.One2many(
        "res.communication", "recruit_id", string="Communications"
    )

    # ── UI control fields ─────────────────────────────────────────────────────
    active1 = fields.Boolean("Active 1")
    active3 = fields.Boolean("Active 3")
    credit_score_bus = fields.Boolean("Credit Score Bus")
    populate_hide_button = fields.Boolean("Hide Button")
    credit_score_hide_button = fields.Boolean("Hide Button", default=False)
    verify_hide_button = fields.Boolean("Hide Button")

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends("genealogy")
    def _compute_job_name(self):
        selection_dict = dict(GENEALOGY_LEVELS)
        for rec in self:
            rec.job_name = selection_dict.get(rec.genealogy, rec.genealogy or "")

    def _compute_recruitment_stage_ageing(self):
        for rec in self:
            rec.days_in_current_recruiting_stage = 0
            today = fields.Datetime.now()
            if rec.state_change_date:
                delta = today - rec.state_change_date
            else:
                delta = today - rec.create_date
            if delta:
                rec.days_in_current_recruiting_stage = delta.days

    def _compute_recruitment_process_ageing(self):
        for rec in self:
            delta = fields.Datetime.now() - rec.create_date
            rec.days_in_recruiting_process = delta.days

    @api.depends("manager_id.related_distributor_id", "related_distributor_id")
    def _compute_related_distributor_id(self):
        for record in self:
            if record.manager_id:
                if record.genealogy != "Distributor":
                    record.related_distributor_id = (
                        record.manager_id.related_distributor_id
                    )
                else:
                    record.related_distributor_id = False

    def _set_related_distributor_id(self):
        for record in self:
            record.related_distributor_id = record.related_distributor_id

    @api.depends("birth_date")
    def _compute_age(self):
        for rec in self:
            rec.age = 0
            if rec.birth_date:
                dob = datetime.datetime.strptime(
                    str(rec.birth_date), "%Y-%m-%d"
                ).date()
                rec.age = relativedelta(fields.Datetime.now().date(), dob).years

    # ─────────────────────────────────────────────────────────────────────────
    # Kanban group-expand
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Always show all active stages in Kanban view."""
        return stages.search([("active", "=", True)], order="sequence asc")

    # ─────────────────────────────────────────────────────────────────────────
    # Default helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _default_stage_id(self):
        return (
            self.env["sf.recruit.stage"]
            .search(
                [("fold", "=", False), ("active", "=", True)],
                order="sequence asc",
                limit=1,
            )
            .id
            or False
        )

    def get_sale_force(self):
        return True  # sf.recruit records are always sales force

    def get_employee_type(self):
        return "sales_force"

    def get_country(self):
        return (
            self.env["res.country"].search([("name", "=", "South Africa")]).id
        )

    def get_formal_name(self):
        if self.first_name and self.last_name:
            return self.first_name + " " + self.last_name

    # ─────────────────────────────────────────────────────────────────────────
    # Onchange helpers
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange("genealogy")
    def on_job_id_type(self):
        if not self.employee_type and self.genealogy:
            self.employee_type = "sales_force"

    @api.onchange("recruiter_id")
    def onchange_recruiter_id(self):
        if not self.manager_id and self.recruiter_id:
            if (
                self.recruiter_id.genealogy == "Manager"
                or self.recruiter_id.is_manager
            ):
                self.manager_id = self.recruiter_id.id
            else:
                if self.recruiter_id.manager_id:
                    self.manager_id = self.recruiter_id.manager_id.id

    @api.onchange("manager_id")
    def _get_distributor(self):
        for rec in self:
            if rec.manager_id:
                rec.related_distributor_id = (
                    rec.manager_id.related_distributor_id.id
                )
            else:
                rec.related_distributor_id = False

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
        if self.last_name:
            self.name = str(self.first_name) + " " + str(self.last_name)
        else:
            self.name = str(self.first_name)

    @api.onchange("last_name")
    def onchange_last_name(self):
        if self.first_name:
            self.name = str(self.first_name) + " " + str(self.last_name)
        else:
            self.name = str(self.first_name)

    @api.onchange("mobile")
    def onchange_mobile(self):
        if self.mobile:
            if (
                re.match(r"^[0-9]\d{10,14}$", self.mobile) is None
                and re.match(r"^[0-9]\d{9}$", self.mobile) is None
            ):
                raise ValidationError("Enter a normal 10 digits Mobile number")
            if len(self.mobile) < 10:
                raise ValidationError("Enter a normal 10 digits Mobile number")
        if self.mobile and self.country_id.code:
            number1 = self.mobile[-9:]
            number = "0" + str(number1)
            parsed = phonenumbers.parse(number, self.country_id.code)
            self.mobile = str(
                phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            )[1:]

    @api.onchange("mobile_2")
    def onchange_mobile_2(self):
        if self.mobile_2:
            if (
                re.match(r"^[0-9]\d{10,14}$", self.mobile_2) is None
                and re.match(r"^[0-9]\d{9}$", self.mobile_2) is None
            ):
                raise ValidationError("Enter a normal 10 digits Mobile number")
            if len(self.mobile_2) < 10:
                raise ValidationError("Enter a normal 10 digits Mobile number")
        if self.mobile_2 and self.country_id.code:
            number1 = self.mobile_2[-9:]
            number = "0" + str(number1)
            parsed = phonenumbers.parse(number, self.country_id.code)
            self.mobile_2 = str(
                phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            )[1:]

    @api.onchange("country_id")
    def onchange_country(self):
        self.onchange_mobile()
        self.onchange_mobile_2()

    @api.onchange("sa_id")
    def on_change_rsa_id(self):
        self.partner_id.on_change_rsa_id()

    # ─────────────────────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────────────────────

    @api.constrains("passport")
    def validate_passport(self):
        if self.passport:
            check_number = any(c.isdigit() for c in self.passport)
            if not check_number:
                raise ValidationError("Not a valid passport number")
            if len(self.passport) < 6:
                raise ValidationError("Not a valid passport number")

    @api.constrains("nationality")
    def check_duplicate_nationality(self):
        if self.nationality:
            self.search_count(
                [
                    ("nationality", "=", self.nationality.id),
                    ("passport", "=", self.passport),
                ]
            )
            # Duplicate check intentionally non-raising (matches original code)

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        # Validate recruiter is not Support Office
        if vals.get("recruiter_id"):
            recruiter = self.env["sf.member"].browse([vals["recruiter_id"]])
            if recruiter and recruiter.genealogy == "Support Office":
                raise UserError(
                    "Sorry, Support Office members are not permitted to recruit."
                )

        # Default stage based on genealogy
        if not vals.get("stage_id"):
            stage_id = self.env["sf.recruit.stage"].search(
                [("fold", "=", False), ("active", "=", True)],
                order="sequence asc",
                limit=1,
            )
            if stage_id:
                vals["stage_id"] = stage_id.id

        if (
            not vals.get("mobile_2")
            and not vals.get("mobile")
            and self.employee_type == "sales_force"
        ):
            raise UserError(_("Mobile - SMS and Mobile - WhatsApp not captured."))

        if not vals.get("mobile_2"):
            vals["mobile_2"] = vals.get("mobile")
        if not vals.get("mobile"):
            vals["mobile"] = vals.get("mobile_2")

        # Compose name
        if (
            not vals.get("name")
            and not vals.get("first_name")
            and not vals.get("last_name")
        ):
            vals["name"] = vals.get("mobile")
            vals["first_name"] = vals.get("mobile")

        if vals.get("recruiter_id") and not vals.get("manager_id"):
            recruiter = self.env["sf.member"].browse([vals["recruiter_id"]])
            vals["manager_id"] = recruiter.manager_id.id

        # Parse RSA ID
        if vals.get("sa_id"):
            vals = self._parse_sa_id(vals)

        if not vals.get("name"):
            if vals.get("first_name") and vals.get("last_name"):
                vals["name"] = vals["first_name"] + " " + vals["last_name"]
                vals["legend_blocked"] = "Blocked"
        vals["partner_name"] = vals.get("name")

        # Normalise mobile numbers on import
        if self._context.get("import_file"):
            vals = self._normalise_mobiles_on_import(vals)

        res = super(SfRecruit, self).create(vals)

        # Propagate state to partner for geodecoding
        if res.state_id and res.partner_id:
            res.partner_id.state_id = res.state_id.id

        # Auto-progress stage via required.field.state rules
        self._check_and_advance_stage(res)

        # Sync member if linked
        if res.member_id:
            if not res.member_id.manager_id and res.manager_id:
                res.member_id.manager_id = res.manager_id.id
                res.member_id.related_distributor_id = (
                    res.related_distributor_id.id
                )

        if not res.manager_id and res.recruiter_id:
            if (
                res.recruiter_id.genealogy == "Manager"
                or res.recruiter_id.is_manager
            ):
                res.manager_id = res.recruiter_id.id
            elif res.recruiter_id.manager_id:
                res.manager_id = res.recruiter_id.manager_id.id

        if not res.known_name and res.name:
            res.known_name = res.name

        if res.name == "False":
            res.name = False
        if res.name and res.name != "False":
            name_list = res.name.split()
            if len(name_list) > 1:
                if not res.first_name:
                    res.first_name = name_list[0]
                if not res.last_name:
                    res.last_name = name_list[-1]
            else:
                if not res.first_name:
                    res.first_name = name_list[0]

        if res.known_name == res.mobile and res.name != res.mobile:
            res.known_name = res.name

        return res

    def write(self, vals):
        _logger.debug(f"sf.recruit.write: {vals}")

        # Validate recruiter is not Support Office
        if vals.get("recruiter_id"):
            recruiter = self.env["sf.member"].browse([vals["recruiter_id"]])
            if recruiter and recruiter.genealogy == "Support Office":
                raise UserError(
                    "Sorry, Support Office members are not permitted to recruit."
                )

        # Stage change — record timestamp and date fields
        if vals.get("stage_id"):
            vals["state_change_date"] = fields.Datetime.now()
            stage = self.env["sf.recruit.stage"].browse([vals.get("stage_id")])
            if stage.name == "Potential Lead":
                vals["potential_lead_date"] = vals["state_change_date"]
            elif stage.name == "Lead":
                vals["lead_date"] = vals["state_change_date"]
            elif stage.name == "Potential Recruit":
                vals["potential_recruit_date"] = vals["state_change_date"]
            elif stage.name == "Recruit":
                vals["recruit_date"] = vals["state_change_date"]
            elif stage.name == "Potential Consultant":
                vals["potential_consultant_date"] = vals["state_change_date"]

        # Fill mobile defaults
        if not vals.get("mobile_2") and not self.mobile_2:
            vals["mobile_2"] = self.mobile
            if vals.get("mobile"):
                vals["mobile_2"] = vals.get("mobile")
        if not vals.get("mobile") and not self.mobile:
            vals["mobile"] = self.mobile_2
            if vals.get("mobile_2"):
                vals["mobile"] = vals.get("mobile_2")

        # Compose name from parts
        if not vals.get("name"):
            fn = vals.get("first_name")
            ln = vals.get("last_name")
            if fn and ln:
                vals["name"] = fn + " " + ln
            elif fn and not ln and self.last_name:
                vals["name"] = fn + " " + self.last_name
            elif ln and not fn and self.first_name:
                vals["name"] = self.first_name + " " + ln
            elif fn:
                vals["name"] = fn

        if self._context.get("import_file"):
            vals = self._normalise_mobiles_on_import(vals)

        res = super(SfRecruit, self).write(vals)

        # Propagate province to partner
        if vals.get("state_id") and res and self.partner_id:
            self.partner_id.state_id = vals["state_id"]

        # Auto-progress stage via required.field.state rules
        if vals.get("stage_id") or any(
            v in vals
            for v in [
                "sa_id", "passport", "manager_id", "first_name", "last_name",
                "mobile", "induction_meeting_attended", "documents_submitted",
            ]
        ):
            self._check_and_advance_stage(self)

        if not self.is_potential_flag:
            if self.stage_id.name == "Potential Consultant":
                self.is_potential_flag = True

        # Sync member record if linked
        if self.member_id:
            if not self.member_id.manager_id and self.manager_id:
                self.member_id.manager_id = self.manager_id.id
                self.member_id.related_distributor_id = (
                    self.related_distributor_id.id
                )
            # Propagate unverified_ address fields
            if any(k.startswith("unverified_") for k in vals.keys()):
                self.member_id.write(
                    {k: v for k, v in vals.items() if k.startswith("unverified_")}
                )

        if not self.manager_id and self.recruiter_id:
            if (
                self.recruiter_id.genealogy == "Manager"
                or self.recruiter_id.is_manager
            ):
                self.manager_id = self.recruiter_id.id
            elif self.recruiter_id.manager_id:
                self.manager_id = self.recruiter_id.manager_id.id

        if self.known_name == self.mobile and self.name != self.mobile:
            self.known_name = self.name

        return res

    def unlink(self):
        # Remove dangling partner when deleting a recruit that has no member yet
        if self.partner_id and not self.member_id:
            self.partner_id.unlink()
        return super(SfRecruit, self).unlink()

    # ─────────────────────────────────────────────────────────────────────────
    # Actions / buttons
    # ─────────────────────────────────────────────────────────────────────────

    def hangup_button(self):
        return {
            "type": "ir.actions.client",
            "tag": "sales_force_support.hangup_action",
        }

    def close_form(self):
        return True

    def save_view_recruit_form(self):
        if self.credit_score_hide_button:
            return self.recruit_form_verification()
        else:
            raise ValidationError("To proceed, please run the Credit Check.")

    def save_view_recruit_verification(self):
        time.sleep(3)
        return self.recruit_form_onboard()

    def save_view_recruit_onboard_form(self):
        self.write({"registration_channel": "contact_centre"})
        return True

    def recruit_form_popup(self):
        if self.partner_id.sa_id:
            self.partner_id.on_change_rsa_id()
        view = self.env.ref("sales_force_support.view_recruit_form")
        self.recruit_date = self.create_date
        return {
            "name": _("Recruit Onboard Form"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "sf.recruit",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "res_id": self.id,
            "target": "new",
        }

    def recruit_form_verification(self):
        view = self.env.ref("sales_force_support.view_recruit_verification")
        return {
            "name": _("Recruit Verification Form"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "sf.recruit",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "res_id": self.id,
            "target": "new",
        }

    def recruit_form_onboard(self):
        view = self.env.ref("sales_force_support.view_recruit_onboard_form")
        return {
            "name": _("Recruit Onboard Form"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "sf.recruit",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "res_id": self.id,
            "target": "new",
        }

    def generate_sales_force_code_for_applicant(self):
        if not (
            self.stage_name == "Recruit"
            or (self.related_stage_id and self.related_stage_id.name == "Recruit")
        ):
            raise ValidationError(
                "Generating Sales Force code is not allowed for this stage."
            )
        if self.sales_force_code:
            raise ValidationError("Recruit already has a Sales Force code.")
        sequence = self.env["ir.sequence"].next_by_code(
            "sales.force.code.sequence"
        )
        self.write({"sales_force_code": sequence})

    def create_member_from_recruit_button(self):
        if not self.manager_id:
            raise ValidationError("Manager is not set")
        try:
            member = self.create_member_from_recruit()
            if not member:
                raise ValidationError(
                    _("Error: Sales Force Member record could not be created")
                )
        except Exception as e:
            if member:
                member.sync_outbound("sf_member", member.id, method="delete")
                _logger.error(
                    f"Reversing remote creation of ({member.id}, "
                    f"{member.sales_force_code}) due to error: {str(e)}"
                )
            else:
                _logger.error(e)

    def create_member_from_recruit(self):
        """Create an sf.member from this sf.recruit record.

        The new member SHARES the same res.partner as the recruit so that all
        personal data (name, address, credit score, etc.) is preserved.
        """
        if self.member_id:
            return self.member_id  # Already created

        member = False
        for recruit in self:
            contact_name = recruit.name
            if not contact_name:
                continue

            member = self.env["sf.member"].create(
                {
                    "name": contact_name,
                    # Share the existing partner — delegation inherits all fields
                    "partner_id": recruit.partner_id.id,
                    "genealogy": "Potential Consultant",  # start as Potential Consultant
                    "manager_id": recruit.manager_id.id,
                    "recruiter_id": recruit.recruiter_id.id,
                    "recruiter_source": recruit.recruiter_source,
                    "recruitment_method": recruit.recruitment_method,
                    "related_distributor_id": recruit.related_distributor_id.id,
                    "sales_force_code": recruit.sales_force_code,
                    "last_contact_date": recruit.last_contact_date,
                    "first_sale_date": recruit.first_sale_date,
                    "employee_type": "sales_force",
                }
            )
            recruit.write({"member_id": member.id})
            recruit.active = False

            if recruit.genealogy == "Consultant":
                recruit.genealogy = "Prospective Consultant"

            recruit.employee_created = False

        return member

    def button_compuscan_checkscore(self):
        _logger.info("sf.recruit.button_compuscan_checkscore entry")
        if self.partner_id.is_rsa_id_valid or self.partner_id.passport:
            consumerview_check = self.button_consumerview_populate()

            if not consumerview_check:
                return self.recruit_form_onboard()

            self.partner_id.button_compuscan_checkscore()

            try:
                score = int(self.partner_id.compuscan_checkscore_nlr)
                if score <= 500:
                    colour = "BLUE"
                elif score <= 618:
                    colour = "RED"
                elif score <= 632:
                    colour = "ORANGE"
                else:
                    colour = "GREEN"
            except (ValueError, TypeError):
                colour = "BLUE"

            self.credit_score = colour

            if not self.partner_id.compuscan_checkscore_date:
                return self.recruit_form_onboard()

            self.credit_score_hide_button = True

            if self.credit_score_hide_button:
                time.sleep(15)
                return self.recruit_form_verification()
            else:
                return self.recruit_form_popup()
        else:
            raise ValidationError(
                _("Credit Vetting failed! Please insert correct ID/Passport")
            )

    def button_consumerview_populate(self):
        self.ensure_one()
        context = {
            "consumerview_pick_first": self.env.context.get(
                "consumerview_pick_first", True
            ),
            "consumerview_ignore_errors": self.env.context.get(
                "consumerview_ignore_errors", False
            ),
            "consumerview_raise_not_found": self.env.context.get(
                "consumerview_raise_not_found", False
            ),
        }
        res = self.partner_id.with_context(**context).button_consumerview_populate()

        if not self.partner_id.consumerview_ref:
            return False

        self.populate_hide_button = True
        vals = {
            "unverified_city": self.partner_id.unverified_city,
            "unverified_state_id": self.partner_id.unverified_state_id.id,
            "unverified_country_id": self.partner_id.unverified_country_id.id,
            "unverified_street": self.partner_id.unverified_street,
            "unverified_suburb": self.partner_id.unverified_suburb,
            "first_name": self.partner_id.first_name,
            "unverified_first_name": self.partner_id.unverified_first_name,
            "last_name": self.partner_id.last_name,
            "unverified_last_name": self.partner_id.unverified_last_name,
            "unverified_zip": self.partner_id.unverified_zip,
        }
        self.write(vals)
        return res

    def button_verify_address(self):
        self.ensure_one()
        name = ""
        if self.unverified_first_name and self.unverified_last_name:
            name = self.unverified_first_name + " " + self.unverified_last_name
        elif self.unverified_last_name:
            name = self.unverified_last_name
        elif self.unverified_first_name:
            name = self.unverified_first_name

        self.verify_hide_button = True
        self.write(
            {
                "city": self.unverified_city,
                "state_id": self.unverified_state_id.id,
                "country_id": self.unverified_country_id.id,
                "street": self.unverified_street,
                "suburb": self.unverified_suburb,
                "first_name": self.unverified_first_name,
                "last_name": self.unverified_last_name,
                "name": name,
                "known_name": name,
                "zip": self.unverified_zip,
                "address_verified": True,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "sf.recruit",
            "view_mode": "form",
            "view_id": self.env.ref(
                "sales_force_support.view_recruit_onboard_form"
            ).id,
            "target": "new",
            "res_id": self.id,
        }

    def button_credit_score_skip(self):
        self.ensure_one()
        self.credit_score = "BLUE"

    # ─────────────────────────────────────────────────────────────────────────
    # Cron-triggered helpers
    # ─────────────────────────────────────────────────────────────────────────

    def stage_unchanged(self):
        """Mark recruits whose stage has not moved for >= 1 hour."""
        for record in self.env["sf.recruit"].search(
            [("create_member", "=", False)]
        ):
            if record.state_change_date:
                time_diff = (
                    fields.Datetime.from_string(fields.Datetime.now())
                    - fields.Datetime.from_string(record.state_change_date)
                )
                hours_diff = math.floor(
                    round(
                        float(time_diff.days) * 24
                        + (float(time_diff.seconds) / 3600)
                    )
                )
                record.stage_not_moved = hours_diff >= 1

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_sa_id(self, vals):
        """Parse South African ID number and populate birth_date, gender."""
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
        current_year = datetime.datetime.now().year % 100
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

    def _normalise_mobiles_on_import(self, vals):
        """Normalise mobile number formats during CSV import."""
        for field in ("mobile", "mobile_2"):
            if vals.get(field) and len(vals[field]) >= 10:
                country_id = self.env["res.country"].search(
                    [("name", "=", "South Africa")]
                )
                if vals.get("country_id"):
                    country_id = self.env["res.country"].browse(
                        [vals.get("country_id")]
                    )
                number1 = vals[field][-9:]
                number = "0" + str(number1)
                try:
                    parsed = phonenumbers.parse(number, country_id.code)
                    formatted = str(
                        phonenumbers.format_number(
                            parsed, phonenumbers.PhoneNumberFormat.E164
                        )
                    )
                    vals[field] = formatted[1:]
                except Exception:
                    pass
        return vals

    def _check_and_advance_stage(self, record):
        """Auto-advance stage if all required fields for the next stage are set."""
        fields_ids = self.env["required.field.state"].search(
            [("state.name", "=", record.stage_id.name)]
        )
        change_state = bool(fields_ids)
        for field_id in fields_ids:
            fname = field_id.field_id.name
            if fname == "sa_id":
                if not record.sa_id and not record.passport:
                    change_state = False
            elif fname == "meeting_count":
                if record.meeting_count == 0:
                    change_state = False
            else:
                value = getattr(record, fname, None)
                if not value:
                    change_state = False
            if fname == "manager_id" and record.genealogy == "Manager":
                change_state = False

        if not fields_ids:
            change_state = False

        if change_state:
            next_stage = self.env["sf.recruit.stage"].search(
                [("sequence", ">", record.stage_id.sequence)],
                order="sequence asc",
                limit=1,
            )
            if next_stage:
                record.stage_id = next_stage.id
                if next_stage.create_member and not record.member_id:
                    try:
                        member = record.create_member_from_recruit()
                        if not member:
                            raise ValidationError(
                                _("Error: Member record could not be created")
                            )
                    except Exception as e:
                        if member:
                            member.sync_outbound(
                                "sf_member", member.id, method="delete"
                            )
                            _logger.error(
                                f"Reversing remote creation: {str(e)}"
                            )
                        else:
                            _logger.error(e)

    # ─────────────────────────────────────────────────────────────────────────
    # Geospatial manager allocation  (source: bb_allocate/models/hr_applicant.py)
    #   • hr.employee  → sf.member
    #   • hr_employee table → sf_member table in raw SQL
    #   • job_id.name  → genealogy (Selection)
    # ─────────────────────────────────────────────────────────────────────────

    manager_blacklist = fields.Char(string="Manager Blacklist")

    def _get_nearby(self, domain=None, order=None, limit=None):
        self.ensure_one()

        partner = self.partner_id

        values = [
            partner.partner_latitude,
            partner.partner_latitude,
            partner.partner_longitude,
        ]

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
            table, sql, params = (
                self.env["sf.member"]._where_calc(domain).get_sql()
            )
            sql = sql.replace('"sf_member__partner_id"', "p")
            query += " " + sql
            values.extend(params)
            query += ") h"

        if order:
            query += " ORDER BY %s" % order

        if limit:
            values.append(limit)
            query += " LIMIT %s"

        self.env.cr.execute(query, values)

        id_distances = self.env.cr.fetchmany()
        while id_distances:
            for *res, distance in id_distances:
                yield self.browse([res[0]]), distance

            id_distances = self.env.cr.fetchmany()

    def button_allocate_manager(self):
        import random
        for applicant in self:
            partner = applicant.partner_id
            partner.write(
                {
                    "street": applicant.street,
                    "zip": applicant.zip,
                    "city": applicant.city,
                    "state_id": applicant.state_id.id,
                    "country_id": applicant.country_id.id,
                }
            )
            partner.geo_localize()

        for applicant in self:
            if applicant.recruiter_id and not applicant.manager_id:
                if applicant.recruiter_id.genealogy in (
                    "Manager",
                    "Prospective Distributor",
                    "Distributor",
                ):
                    applicant.manager_id = applicant.recruiter_id
                else:
                    applicant.manager_id = applicant.recruiter_id.manager_id
                return

            domain = [
                ("genealogy", "in", ("Manager", "Prospective Distributor")),
                ("active_status", "=", "active1"),
            ]

            if applicant.manager_id and applicant.manager_blacklist:
                self.manager_blacklist += ",%s" % applicant.manager_id.id
            elif applicant.manager_id:
                self.manager_blacklist = str(applicant.manager_id.id)

            if self.manager_blacklist:
                domain.append(("id", "not in", self.manager_blacklist.split(",")))

            order = "distance"

            if (
                applicant.partner_id.partner_longitude
                and applicant.partner_id.partner_latitude
            ):
                distance = 1.0

                lon_min = ("partner_id.partner_longitude", ">=",
                           applicant.partner_id.partner_longitude - distance)
                lon_max = ("partner_id.partner_longitude", "<=",
                           applicant.partner_id.partner_longitude + distance)
                lat_min = ("partner_id.partner_latitude", ">=",
                           applicant.partner_id.partner_latitude - distance)
                lat_max = ("partner_id.partner_latitude", "<=",
                           applicant.partner_id.partner_latitude + distance)

                domain.extend([lon_min, lon_max, lat_min, lat_max])

                employees = [p.id for p, d in self._get_nearby(domain, order=order)]

                for term in [lon_min, lon_max, lat_min, lat_max]:
                    domain.remove(term)
            else:
                employees = False

            order = None

            state_domain_term = None
            if applicant.state_id:
                state_domain_term = ("state_id", "=", applicant.state_id.id)
                domain.append(state_domain_term)

            if applicant.country_id:
                country_domain_term = ("country_id", "=", applicant.country_id.id)
                domain.append(country_domain_term)
            else:
                raise UserError(_("Consultant address is not set"))

            if not employees and applicant.city:
                city_domain_term = ("city", "=", applicant.city)
                domain.append(city_domain_term)
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(city_domain_term)

            if not employees and state_domain_term:
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(state_domain_term)

            if not employees:
                employees = self.env["sf.member"].search(domain, order=order)

            if employees:
                if isinstance(employees[0], int):
                    manager_id = employees[0]
                else:
                    manager_id = employees[0][0]
                    if not isinstance(employees[0], int):
                        manager_id = manager_id.id

                applicant.manager_id = manager_id

                consult_domain = [
                    ("manager_id", "=", manager_id),
                    ("four_months_sales", ">", 0),
                    ("active_status", "=", "active1"),
                ]
                try:
                    recruiter_id = random.choice(
                        [r.id for r in self.env["sf.member"].search(consult_domain)]
                    )
                except IndexError:
                    applicant.recruiter_id = applicant.consultant_id = manager_id
                else:
                    applicant.recruiter_id = applicant.consultant_id = recruiter_id
            else:
                raise UserError(_("Could not find a manager nearby"))


class RequiredFieldState(models.Model):
    """Defines which fields must be set before auto-advancing to the next
    recruitment stage. Previously named FieldsRequirdState in botle_buhle_custom."""

    _name = "required.field.state"
    _description = "Required Fields per Stage"

    field_id = fields.Many2one("ir.model.fields", "Field")
    # NOTE: updated from hr.recruitment.stage → sf.recruit.stage
    state = fields.Many2one("sf.recruit.stage", "Stage")
