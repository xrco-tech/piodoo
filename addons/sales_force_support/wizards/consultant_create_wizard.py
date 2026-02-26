# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/wizards/consultant_create_wizard.py

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
import phonenumbers
import re

_logger = logging.getLogger(__name__)


DEFAULT_PARTNER_FIELDS = [
    "id",
    "name",
    "first_name",
    "last_name",
    "mobile",
    "consultant_id",
    "view_model",
    "view_res_id",
]

WHITELISTED_WRITE_PARTNER_FIELDS = [
    "name",
    "first_name",
    "last_name",
    "mobile_2",
    "street",
    "suburb",
    "city",
    "state_id",
    "country_id",
    "mobile",
    "consultant_id",
    "recruiter_id",
    "recruiter_source",
    "sa_id",
    "passport",
    "consultant_id",
    "manager_id",
    "distributor_id",
    "sales_force_code",
    "known_name",
    "last_contact_date",
    "last_contact_type",
    "mobile_opt_out",
    "mobile_is_invalid",
]
WHITELISTED_CREATE_PARTNER_FIELDS = WHITELISTED_WRITE_PARTNER_FIELDS
WHITELISTED_READ_PARTNER_FIELDS = (
    WHITELISTED_WRITE_PARTNER_FIELDS
    + DEFAULT_PARTNER_FIELDS
    + [
        "unverified_first_name",
        "unverified_last_name",
        "unverified_street",
        "unverified_suburb",
        "unverified_city",
        "unverified_state_id",
        "unverified_country_id",
        "unverified_zip",
        "compuscan_checkscore_cpa",
        "compuscan_checkscore_nlr",
        "compuscan_checkscore_date",
        "credit_score",
        "create_date_bb",
    ]
)

# Change From v14 after upgrade to v17
DEFAULT_EMPLOYEE_FIELDS = [
    "id",
    "sales_force_code",
    "name",
    "first_name",
    "last_name",
    "mobile",
    "genealogy",
    "related_distributor_id",
    "manager_id",
    "view_model",
    "view_res_id",
]
# Change From v14 after upgrade to v17
WHITELISTED_WRITE_EMPLOYEE_FIELDS = [
    "name",
    "sales_force_code",
    "first_name",
    "last_name",
    "mobile_2",
    "street",
    "suburb",
    "city",
    "state_id",
    "country_id",
    "zip",
    "mobile",
    "sa_id",
    "passport",
    "related_distributor_id",
    "manager_id",
    "genealogy",
    "is_credit_check",
    "recruiter_id",
    "gender",
    "birth_date",
    "credit_score",
    "recruiter_source",
    "consultant_id",
    "manager_id",
    "distributor_id",
    "known_name",
    "last_contact_date",
    "last_contact_type",
    "sales_force",
    "manager_sf_code",
    "mobile_opt_out",
    "mobile_is_invalid",
]

WHITELISTED_CREATE_EMPLOYEE_FIELDS = WHITELISTED_WRITE_EMPLOYEE_FIELDS
WHITELISTED_READ_EMPLOYEE_FIELDS = (
    WHITELISTED_WRITE_EMPLOYEE_FIELDS
    + DEFAULT_EMPLOYEE_FIELDS
    + [
        "unverified_first_name",
        "unverified_last_name",
        "unverified_street",
        "unverified_suburb",
        "unverified_city",
        "unverified_state_id",
        "unverified_country_id",
        "unverified_zip",
        "compuscan_checkscore_cpa",
        "compuscan_checkscore_nlr",
        "compuscan_checkscore_date",
        "credit_score",
        "active1",
        "active3",
        "active6",
        "inactive",
        "create_date_bb",
    ]
)

DEFAULT_APPLICANT_FIELDS = [
    "id",
    "name",
    "first_name",
    "last_name",
    "mobile",
    "stage_id",
    "recruiter_id",
    "view_model",
    "view_res_id",
]


class ConsultantCreateWizard(models.TransientModel):
    _name = "consultant.create.wizard"
    _description = "Consultant Create Wizard"

    full_name = fields.Char(string="Full Name")
    # mobile_country_id = fields.Many2one('res.country', 'Mobile Country', tracking=True, default=lambda self: self.env['res.country'].search([('name', '=', 'South Africa')], limit=1).id,)
    mobile = fields.Char(string="Mobile")

    id_type = fields.Selection(
        [("sa_id", "ID Number"), ("passport", "Passport")], string="ID Type"
    )

    sa_id = fields.Char(string="ID Number")
    passport = fields.Char(string="Passport")

    credit_check_consent = fields.Selection(
        [("yes", "Yes"), ("no", "No")], string="Conduct Credit Check?"
    )

    recruiter_source = fields.Selection(
        [("internal", "Internal"), ("external", "External")], string="Recruiter Source"
    )
    # Change From v14 after upgrade to v17
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
    recruiter_id = fields.Many2one("sf.member", string="Recruited By")
    manager_id = fields.Many2one("sf.member", string="Manager")
    street = fields.Char(string="Street")
    suburb = fields.Char(string="Suburb")
    city = fields.Char(string="City")
    state_id = fields.Many2one("res.country.state", string="Province/State")
    zip = fields.Char(string="Zip")
    country_id = fields.Many2one(
        "res.country",
        string="Country",
        default=lambda self: self.env["res.country"]
        .search([("name", "=", "South Africa")], limit=1)
        .id,
    )
    sales_force_code = fields.Char("Sales Force Code")

    # New Code Start
    mobile_country_code_ids = fields.Many2one('res.country', string="Mobile Country", default=lambda self: self.env['res.country'].search([('name', '=', 'South Africa')], limit=1).id)
    mobile_country_code_display = fields.Char(compute="_compute_mobile_country_code", store=False)
    mobile_full_display = fields.Char(compute="_compute_full_mobile")

    @api.depends('mobile', 'mobile_country_code_display')
    def _compute_full_mobile(self):
        for rec in self:
            if rec.mobile and rec.mobile_country_code_ids:
                # Get the number of digits required for the selected country
                min_digits = rec.mobile_country_code_ids.min_digit or 8  # fallback to 8 if not set
                max_digits = rec.mobile_country_code_ids.max_digit or 9  # fallback to 9 if not set

                # Remove leading zeros for checking
                number_without_leading_zero = str(self.mobile).lstrip('0')

                # Dynamic regex: must match between min_digits and max_digits
                regex_pattern = f"^\\d{{{min_digits},{max_digits}}}$"
                if not re.match(regex_pattern, number_without_leading_zero):
                    raise ValidationError(_(
                        f"Enter a valid {self.mobile_country_code_ids.name} Country Mobile number "
                        f"with {min_digits} to {max_digits} digits"
                    ))

                # Format mobile with country code using phonenumbers
                try:
                    number_with_country_code = phonenumbers.parse(number_without_leading_zero, rec.mobile_country_code_ids.code)
                    rec.mobile_full_display = str(phonenumbers.format_number(
                        number_with_country_code, phonenumbers.PhoneNumberFormat.E164
                    ))[1:]  # remove leading '+'
                except phonenumbers.NumberParseException:
                    raise ValidationError(_("Invalid Mobile number"))
            else:
                rec.mobile_full_display = ""

    @api.depends('mobile_country_code_ids')
    def _compute_mobile_country_code(self):
        for rec in self:
            if rec.mobile_country_code_ids and rec.mobile_country_code_ids.phone_code:
                rec.mobile_country_code_display = f"+{rec.mobile_country_code_ids.phone_code}"
            else:
                rec.mobile_country_code_display = ""
    # New Code End

    @api.onchange("manager_id")
    def onchange_country(self):
        if self.manager_id:
            self.country_id = self.manager_id.country_id

    @api.onchange("recruiter_id")
    def onchange_manager(self):
        if self.recruiter_id:
            self.manager_id = self.recruiter_id.manager_id.id

    def _get_country_name_from_code(self, phone_code):
        options = self._get_country_options()
        for code, label in options:
            if code == str(phone_code):
                # label looks like " South Africa (+27)"
                # Extract country name before '('
                return label.split('(')[0].strip()
        return phone_code

    def create_consultant(self):
        if not self.recruiter_source:
            raise UserError("Recruiter Source is required.")

        # Change From v14 after upgrade to v17
        if not self.recruitment_method:
            raise UserError("Recruitment Method is required.")

        # genealogy selection field replaces hr.job lookup
        stage_name = "Potential Consultant"
        recruit_stage_id = (
            self.env["sf.recruit.stage"]
            .search([("name", "=", stage_name)], limit=1)
            .id
        )

        vals = {
            "sales_force": True,
            "genealogy": "potential_consultant",
            "stage_id": recruit_stage_id,
            # Change From v14 after upgrade to v17
            "recruitment_method": self.recruitment_method,
        }

        if self.mobile_full_display and self.mobile_full_display != "":
            # Check for duplicates
            check_mobile_count = self.env['res.partner'].search_count([('mobile', '=', self.mobile_full_display), ('customer', '!=', True)])
            if check_mobile_count > 0:
                raise UserError(_(f"Duplicate Mobile Number not permitted. Mobile {self.mobile_full_display} already exists"))

            # Assign formatted number
            self.mobile = self.mobile_full_display
            vals['mobile'] = self.mobile
            vals['mobile_2'] = self.mobile

        if self.full_name:
            full_name_arr = str(self.full_name).split(" ")
            last_name = full_name_arr[-1]

            # Applified Developer : Comment Start, For old code => Issue #Universal
            # first_name = full_name_arr[0]
            # Applified Developer : Comment End, For old code => Issue #Universal

            # Applified Developer : Comment Start, For old code => Issue #Universal
            first_name = " ".join(full_name_arr[:-1])
            # Applified Developer : Comment End, For old code => Issue #Universal

            vals["first_name"] = first_name
            vals["last_name"] = last_name
            vals["known_name"] = f"{first_name} {last_name}"
            vals["name"] = self.full_name

        if self.id_type == "sa_id" and self.sa_id:
            check_sa_id_count = (
                self.env["res.partner"]
                .env["res.partner"]
                .search_count([("sa_id", "=", self.sa_id)])
            )
            print(f"Checked duplicate sa id numbers: {check_sa_id_count}")
            if check_sa_id_count > 0:
                raise ValidationError(
                    _(
                        f"Duplicate SA ID Number not permitted. SA ID Number {self.sa_id} already exists"
                    )
                )

            vals["sa_id"] = self.sa_id

        if self.credit_check_consent == "yes":
            vals["is_credit_check"] = True

        if self.id_type == "passport" and self.passport:
            check_passport_count = self.env["res.partner"].search_count(
                [("passport", "=", self.passport)]
            )
            print(f"Checked duplicate passport numbers: {check_passport_count}")
            if check_passport_count > 0:
                raise ValidationError(
                    _(
                        f"Duplicate Passport Number not permitted. Passport Number {self.passport} already exists"
                    )
                )

            vals["passport"] = self.passport

        if "sa_id" in vals or "passport" in vals:
            stage_name = "Lead"

        if self.recruiter_source == "external":
            vals["recruiter_source"] = "external"
            vals["street"] = self.street
            vals["suburb"] = self.suburb
            vals["city"] = self.city
            vals["state_id"] = self.state_id.id
            vals["country_id"] = self.country_id.id
            stage_name = "Potential Recruit"
        elif self.recruiter_source == "internal" and self.recruiter_id:
            vals["recruiter_source"] = "internal"
            vals["recruiter_id"] = self.recruiter_id.id
            vals["manager_id"] = self.recruiter_id.manager_id.id
        # Change From v14 after upgrade to v17
        elif self.recruitment_method == "pay_in_sheet" and self.manager_id:
            vals.update(
                {
                    "recruiter_source": "internal",
                    "recruiter_id": (
                        self.recruiter_id.id
                        if self.recruiter_id
                        else self.manager_id.id
                    ),
                    "manager_id": (
                        self.manager_id.id
                        if self.manager_id
                        else (
                            self.recruiter_id.manager_id.id
                            if self.recruiter_id
                            else False
                        )
                    ),
                }
            )

        recruit_stage_id = (
            self.env["sf.recruit.stage"]
            .search([("name", "=", stage_name)], limit=1)
            .id
        )
        vals["stage_id"] = recruit_stage_id
        # Change From v14 after upgrade to v17
        vals["registration_channel"] = "manual_capture"
        recruit = self.env["sf.recruit"].create(vals)

        if (
            recruit
            and self.id_type == "sa_id"
            and self.sa_id
            and self.credit_check_consent == "yes"
        ):
            vals["is_credit_check"] = True
            recruit.button_compuscan_checkscore()
        else:
            recruit.button_credit_score_skip()

        if self.recruiter_source == "external":
            area_managers_count = self.env["sf.member"].search_count(
                [
                    ("genealogy", "in", ["manager", "prospective_distributor"]),
                    ("country_id", "=", self.country_id.id),
                    ("state_id", "=", self.state_id.id),
                ]
            )
            print(
                f"Checked areas within the province/state at least before attempting to allocate manager: {area_managers_count}"
            )
            if area_managers_count > 0:
                recruit.button_allocate_manager()
            else:
                raise ValidationError(
                    _(
                        f"Sorry! We could not find a manager within the specified Province/State and Country"
                    )
                )

        # Change From v14 after upgrade to v17
        consultant = None
        try:
            consultant = recruit.create_employee_from_applicant()
            if not consultant:
                raise ValidationError(
                    _(f"Error: Consultant record could not be created")
                )
            consultant_id = recruit.emp_id.id
            self.sales_force_code = recruit.emp_id.sales_force_code
            if self.recruitment_method == "pay_in_sheet":
                self.env["sf.member"].search([("id", "=", consultant_id)]).write(
                    {
                        "active_status": "pay_in_sheet_pending",
                        "genealogy": "consultant",
                    }
                )
            else:
                self.env["sf.member"].search([("id", "=", consultant_id)]).write(
                    {
                        "active_status": "potential_consultant",
                    }
                )
        except Exception as e:
            if consultant:
                recruit.emp_id.sync_outbound(
                    "sf_member", recruit.emp_id.id, method="delete"
                )
                _logger.error(
                    f"Reversing the remote creation of ({recruit.emp_id.id}, {recruit.emp_id.sales_force_code}) due to error: {str(e)}"
                )
            else:
                _logger.error(e)

        view_id = self.env.ref(
            "sales_force_support.display_create_consultant_wizard_view"
        ).id
        return {
            "name": _("Consultant Successfully Created"),
            "type": "ir.actions.act_window",
            "res_model": "sf.member",
            "view_mode": "form",
            "view_type": "form",
            "views": [(view_id, "form")],
            "target": "new",
            "res_id": consultant_id,
        }
