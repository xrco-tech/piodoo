# -*- coding: utf-8 -*-
# Sources merged (5 modules → 1 file):
#   botle_buhle_custom/models/res_partner.py      — personal fields, WhatsApp, CRUD
#   bbb_sales_force_genealogy/models/res_partner.py — remote_id, country_name, sync
#   partner_compuscan/models/res_partner.py        — Compuscan CheckScore
#   partner_consumerview/models/res_partner.py     — ConsumerView KYC / address
#   bb_allocate/models/res_partner.py              — geospatial consultant allocation
#
# Key transformations applied:
#   hr.employee → sf.member
#   hr.applicant → sf.recruit
#   view_model Selection: hr.employee→sf.member, hr.applicant→sf.recruit
#   config params: botle_buhle_custom.* / bbb_sales_force_genealogy.* → sales_force_support.*
#   raw SQL: hr_employee → sf_member  (table name)
#   job_id.name → genealogy  (Selection field on sf.member)

import json
import logging
import re
import time
import datetime
from datetime import datetime as dt

import requests
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Phase 9 will populate controllers/main.py; import defensively
try:
    from ..controllers.main import format_msisdn, MSISDNFormat
except ImportError:
    format_msisdn = None
    MSISDNFormat = None

_logger = logging.getLogger(__name__)

# ── WhatsApp Cloud API constants ──────────────────────────────────────────────
WA_API_MESSAGING_PRODUCT = "whatsapp"
WA_API_RECIPIENT_TYPE = "individual"
WA_API_LANGUAGE_POLICY = "deterministic"
WHATSAPP_API_VERSION = "v21.0"
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ── Personal data (source: botle_buhle_custom) ───────────────────────────
    first_name = fields.Char("First Name", tracking=True)
    last_name = fields.Char("Last Name", tracking=True)
    known_name = fields.Char("Known Name", tracking=True)
    age = fields.Integer("Age", compute="_compute_age", tracking=True)
    mobile = fields.Char(unique=True, string="Mobile", tracking=True)
    mobile_2 = fields.Char("Mobile 2", tracking=True)
    email_2 = fields.Char("Email 2", tracking=True)
    gender = fields.Selection(
        [("male", "Male"), ("female", "Female")], string="Gender", tracking=True
    )
    sa_id = fields.Char("ID Number")
    passport = fields.Char("Passport", tracking=True)
    nationality = fields.Many2one("res.country", "Nationality", tracking=True)
    birth_date = fields.Date("Birth Date", tracking=True)
    bad_debts = fields.Integer("Bad Debts")
    image = fields.Binary("Image")
    suburb = fields.Char("Suburb", tracking=True)
    district = fields.Char("District", tracking=True)
    credit_score = fields.Char("Credit Score", default="BLUE")
    potential_lead_date = fields.Date("Potential Lead Date")
    customer = fields.Boolean("Customer")
    vetting_ids = fields.One2many("res.vetting", "partner_id", string="Vettings")
    emp_company = fields.Char("Distributor Company Name")
    reg_no = fields.Char("Reg. No.")
    vat = fields.Char("VAT No.")
    paye = fields.Char("PAYE")
    last_contact_type = fields.Char(string="Last Communication Type", tracking=True)
    last_contact_date = fields.Date("Last Contact Date", tracking=True)
    mobile_opt_out = fields.Boolean(
        string="Opted Out", default=False, tracking=True
    )
    mobile_opt_out_date = fields.Datetime("Mobile Opt Out Date", tracking=True)
    mobile_2_opt_out = fields.Boolean(
        string="Opted Out (Mobile 2)", default=False, tracking=True
    )
    mobile_2_opt_out_date = fields.Datetime("Mobile 2 Opt Out Date", tracking=True)
    mobile_is_invalid = fields.Boolean(
        string="Mobile Is Invalid", default=False, tracking=True
    )
    is_credit_check = fields.Boolean(string="Is Credit Check")

    # Unverified address fields (populated by ConsumerView before confirmation)
    unverified_city = fields.Char("Unverified City")
    unverified_address = fields.Char("Unverified Address")
    unverified_state_id = fields.Many2one("res.country.state", "Unverified Province")
    unverified_country_id = fields.Many2one("res.country", "Unverified Country")
    unverified_street = fields.Char("Unverified Street")
    unverified_suburb = fields.Char("Unverified Suburb")
    unverified_first_name = fields.Char("Unverified First Name")
    unverified_last_name = fields.Char("Unverified Last Name")
    unverified_zip = fields.Char("Unverified Zip Code")
    address_verified = fields.Boolean(string="Address Verified", tracking=True)

    # View model routing  (Selection values updated: hr.* → sf.*)
    view_model = fields.Selection(
        [
            ("sf.recruit", "Recruit"),
            ("sf.member", "Sales Force Member"),
            ("res.partner", "Partner"),
        ],
        string="View Model",
        compute="compute_view_model",
    )
    view_res_id = fields.Integer("View Model ID")

    # Relationships to sf.member  (was hr.employee)
    consultant_id = fields.Many2one("sf.member", string="Consultant")
    manager_id = fields.Many2one("sf.member", string="Manager")
    related_distributor_id = fields.Many2one("sf.member", string="Distributor")
    recruiter_id = fields.Many2one("sf.member", string="Recruiter")
    related_sfm_id = fields.Many2one(
        "sf.member", string="Related Sales Force Member"
    )
    related_sfm_code = fields.Char(
        related="related_sfm_id.sales_force_code",
        string="Related Sales Force Code",
    )
    manager_sfm_code = fields.Char(
        related="manager_id.sales_force_code", string="Manager Sales Force Code"
    )
    manager_mobile = fields.Char(
        related="manager_id.partner_id.mobile", string="Manager Mobile"
    )

    create_date_bb = fields.Datetime("Create Date", default=fields.Datetime.now)
    sales_force_code = fields.Char(string="Sales Force Code")

    category_title = fields.Char(string="Title", compute="_compute_category_title")
    is_rsa_id_valid = fields.Boolean(
        string="Check Valid RSA ID", default=False, tracking=True
    )

    # ── Distribution (source: botle_buhle_custom + bbb_sales_force_genealogy) ─
    distribution_id = fields.Many2one("sf.distribution", string="Distribution")

    # ── Sync tracking (source: bbb_sales_force_genealogy) ────────────────────
    remote_id = fields.Integer(string="Remote Primary Key", tracking=True)
    last_outbound_sync_date = fields.Datetime(string="Last Outbound Sync Date")
    last_inbound_sync_date = fields.Datetime(string="Last Inbound Sync Date")
    country_name = fields.Char(compute="_compute_mobile_country_name")

    # ── Compuscan CheckScore (source: partner_compuscan) ─────────────────────
    compuscan_checkscore_cpa = fields.Char(string="Compuscan CheckScore CPA Score")
    compuscan_checkscore_nlr = fields.Char(string="Compuscan CheckScore NLR Score")
    compuscan_checkscore_date = fields.Datetime(string="Compuscan CheckScore Date")
    compuscan_checkscore_risk = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("high", "High risk"),
            ("average", "Average risk"),
            ("low", "Low risk"),
        ],
        string="Compuscan CheckScore Status",
    )

    # ── ConsumerView (source: partner_consumerview) ───────────────────────────
    consumerview_ref = fields.Char(string="ConsumerView Reference")

    # ── Geospatial allocation (source: bb_allocate) ───────────────────────────
    consultant_blacklist = fields.Char(string="Consultant Blacklist")

    # ─────────────────────────────────────────────────────────────────────────
    # WhatsApp Cloud API  (source: botle_buhle_custom)
    #   config params: botle_buhle_custom.* → sales_force_support.*
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _whatsapp_cloud_send_message_with_retry(
        headers,
        data,
        phone_number_id,
        max_retries=MAX_RETRIES,
        initial_delay=INITIAL_RETRY_DELAY,
    ):
        url = (
            f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
            f"/{phone_number_id}/messages"
        )
        response = None
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, data=data)
                if response.status_code == 200:
                    return response
                elif response.status_code in RETRYABLE_STATUS_CODES:
                    delay = initial_delay * (2 ** attempt)
                    if (
                        response.status_code == 429
                        and "Retry-After" in response.headers
                    ):
                        try:
                            delay = int(response.headers["Retry-After"])
                        except (ValueError, TypeError):
                            pass
                    _logger.warning(
                        f"Request failed with status {response.status_code}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    return response
            except ConnectionError:
                if attempt == max_retries - 1:
                    raise
                delay = initial_delay * (2 ** attempt)
                _logger.warning(f"Connection error. Retrying in {delay}s...")
                time.sleep(delay)
        return response

    @api.model
    def send_whatsapp_template_message(
        self, msisdn, template_name, param_location, *placeholders
    ):
        if not msisdn:
            raise ValidationError("No value provided for msisdn parameter")
        cfg = self.env["ir.config_parameter"].sudo()
        bbbot_sender = {
            "token": cfg.get_param(
                "sales_force_support.whatsapp_bbbot_sender_token"
            ),
            "namespace": cfg.get_param(
                "sales_force_support.whatsapp_bbbot_sender_namespace"
            ),
            "phone_number_id": cfg.get_param(
                "sales_force_support.whatsapp_bbbot_sender_phone_number_id"
            ),
        }
        headers = {
            "Authorization": f"Bearer {bbbot_sender['token']}",
            "Content-Type": "application/json",
        }
        parameters = [{"type": "text", "text": p} for p in placeholders]
        components = []
        if param_location == "header":
            components.append({"type": "header", "parameters": parameters})
        else:
            components.append({"type": "body", "parameters": parameters})
        data = json.dumps(
            {
                "messaging_product": WA_API_MESSAGING_PRODUCT,
                "recipient_type": WA_API_RECIPIENT_TYPE,
                "to": msisdn,
                "type": "template",
                "template": {
                    "namespace": bbbot_sender["namespace"],
                    "name": template_name,
                    "language": {
                        "code": "en",
                        "policy": WA_API_LANGUAGE_POLICY,
                    },
                    "components": components,
                },
            }
        )
        return ResPartner._whatsapp_cloud_send_message_with_retry(
            headers, data, bbbot_sender["phone_number_id"]
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints / validation helpers
    # ─────────────────────────────────────────────────────────────────────────

    @api.constrains("sa_id")
    def check_duplicate_id_number(self):
        if self.sa_id:
            count_no = self.search_count([("sa_id", "=", self.sa_id)])
            if count_no > 1:
                raise ValidationError(_("Duplicate ID Number not permitted"))

    def validate_rsa_id_number(self, rsa_id_number):
        """Validates a South African ID number via Luhn algorithm."""
        if not (rsa_id_number.isdigit() and len(rsa_id_number) == 13):
            return False

        def luhn_checksum(number: str) -> bool:
            total = 0
            for i, digit in enumerate(number[::-1]):
                n = int(digit)
                if i % 2 == 1:
                    n *= 2
                    if n > 9:
                        n -= 9
                total += n
            return total % 10 == 0

        return luhn_checksum(rsa_id_number)

    def validate_passport_number(self, passport_number, min_length=6):
        """Validates a passport number (alphanumeric, min length, mixed chars)."""
        return (
            passport_number.isalnum()
            and len(passport_number) >= min_length
            and any(c.isalpha() for c in passport_number)
            and any(c.isdigit() for c in passport_number)
        )

    @api.onchange("sa_id")
    def on_change_rsa_id(self):
        if not self.sa_id:
            self.is_rsa_id_valid = False
            return

        number = self.sa_id
        if len(number) != 13:
            self.is_rsa_id_valid = False
            return
        try:
            int(number)
        except ValueError:
            self.is_rsa_id_valid = False
            return

        current_year = datetime.datetime.now().year % 100
        prefix = "19" if current_year <= int(number[0:2]) else "20"
        year = int(prefix + number[0:2])
        month = int(number[2:4])
        day = int(number[4:6])
        gender_num = int(number[6:10])

        if not (1 <= month <= 12) or not (1 <= day <= 31):
            self.is_rsa_id_valid = False
            return

        try:
            month_str = str(month).zfill(2)
            day_str = str(day).zfill(2)
            self.birth_date = f"{year}-{month_str}-{day_str}"
            self.gender = "female" if gender_num <= 4999 else "male"

            checksum = int(number[12])
            total = 0
            for i in range(12):
                digit = int(number[i])
                if i % 2 == 0:
                    total += digit
                else:
                    doubled = digit * 2
                    total += doubled - 9 if doubled > 9 else doubled

            if (10 - (total % 10)) % 10 != checksum:
                self.is_rsa_id_valid = False
                return
        except Exception:
            self.is_rsa_id_valid = False
            return

        self.is_rsa_id_valid = True

    # ─────────────────────────────────────────────────────────────────────────
    # Computed field methods
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_category_title(self):
        for rec in self:
            member = rec.env["sf.member"].search([("partner_id", "=", rec.id)])
            if member:
                rec.category_title = member.genealogy or "Sales Force Member"
                continue

            recruit = rec.env["sf.recruit"].search([("partner_id", "=", rec.id)])
            if recruit:
                rec.category_title = recruit.stage_id.name
                continue

            rec.category_title = "Customer"

    def compute_view_model(self):
        for record in self:
            member = self.env["sf.member"].search(
                [("partner_id", "=", record.id)], limit=1
            )
            if member:
                record.update(
                    {
                        "view_model": "sf.member",
                        "view_res_id": member.id,
                        "manager_id": member.manager_id.id,
                        "related_distributor_id": member.related_distributor_id.id,
                        "sales_force_code": member.sales_force_code,
                    }
                )
                continue

            recruit = self.env["sf.recruit"].search(
                [("partner_id", "=", record.id)], limit=1
            )
            if recruit:
                record.update(
                    {
                        "view_model": "sf.recruit",
                        "view_res_id": recruit.id,
                        "manager_id": recruit.manager_id.id,
                        "related_distributor_id": recruit.related_distributor_id.id,
                        "sales_force_code": recruit.sales_force_code,
                    }
                )
                continue

            record.update(
                {
                    "view_model": "res.partner",
                    "view_res_id": record.id,
                    "manager_id": record.consultant_id.manager_id.id,
                    "related_distributor_id": (
                        record.consultant_id.related_distributor_id.id
                    ),
                    "sales_force_code": record.sales_force_code,
                }
            )

    @api.depends("birth_date")
    def _compute_age(self):
        for rec in self:
            rec.age = 0
            if rec.birth_date:
                dob = datetime.datetime.strptime(
                    str(rec.birth_date), "%Y-%m-%d"
                ).date()
                rec.age = relativedelta(fields.Datetime.now().date(), dob).years

    def _compute_district(self):
        for rec in self:
            rec.district = False
            apikey = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("base_geolocalize.google_map_api_key")
            )
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            province = rec.state_id.name if rec.state_id else ""
            country = rec.country_id.name if rec.country_id else ""
            city = rec.city if rec.city else ""
            address = f"{city} {province} {country}"
            params = {
                "sensor": "false",
                "address": address,
                "key": apikey,
                "components": f"country:{country}",
            }
            result = requests.get(url, params).json()
            if (
                result["status"] == "OK"
                and "results" in result
                and result["results"]
            ):
                for component in result["results"][0]["address_components"]:
                    if "administrative_area_level_2" in component["types"]:
                        rec.district = component["long_name"]
                        break

    @api.depends("mobile")
    def _compute_mobile_country_name(self):
        for rec in self:
            rec.country_name = self._get_mobile_country_name(
                mobile_number=rec.mobile
            )

    def _get_mobile_country_name(self, mobile_number):
        if not mobile_number:
            return None
        sanitized = re.sub(r"[^0-9]", "", mobile_number)
        phone_code = re.match(r"^(\d{3}|\d{2})", sanitized)
        if not phone_code:
            return None
        phone_code = phone_code.group(1)

        country_records = self.env["res.country"].search_read(
            [("phone_code", "=", phone_code)], fields=["name", "phone_code"]
        )
        if not country_records and len(phone_code) == 3:
            phone_code = phone_code[:2]
            country_records = self.env["res.country"].search_read(
                [("phone_code", "=", phone_code)], fields=["name", "phone_code"]
            )
        return country_records[0].get("name") if country_records else None

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD overrides — merged from botle_buhle_custom + bbb_sales_force_genealogy
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        # ── SA ID validation ───────────────────────────────────────────────
        if vals.get("sa_id"):
            if not self.validate_rsa_id_number(vals["sa_id"]):
                raise ValidationError("Invalid RSA ID Number.")
            vals["is_rsa_id_valid"] = True
            if self.search_count([("sa_id", "=", vals["sa_id"])]) > 0:
                raise ValidationError("Duplicate ID Number not permitted.")

        # ── Passport ───────────────────────────────────────────────────────
        if vals.get("passport"):
            vals["passport"] = vals["passport"].upper()
            if (
                self.search_count([("passport", "=", vals["passport"])]) > 0
            ):
                raise ValidationError("Duplicate Passport not permitted")

        # ── Mobile formatting + duplicate check ────────────────────────────
        if format_msisdn and MSISDNFormat:
            for field in ("mobile", "mobile_2", "phone"):
                if vals.get(field):
                    formatted = format_msisdn(vals[field], MSISDNFormat.E164.value)
                    if formatted:
                        formatted = formatted[1:]
                        vals[field] = formatted
                        dup = self.env["res.partner"].search_count(
                            [
                                "|",
                                "|",
                                ("mobile", "=", formatted),
                                ("mobile_2", "=", formatted),
                                ("phone", "=", formatted),
                                ("customer", "!=", True),
                            ]
                        )
                        if dup > 0:
                            raise ValidationError(
                                f"Duplicate mobile number for field {field}, "
                                f"value {formatted}"
                            )
                    else:
                        raise ValidationError(
                            f"Invalid mobile number for field {field}"
                        )

        # ── Name construction from first_name / last_name ──────────────────
        if not vals.get("name"):
            fn = vals.get("first_name")
            ln = vals.get("last_name")
            if fn and ln:
                vals["name"] = f"{fn} {ln}"
            elif fn:
                vals["name"] = fn
            elif ln:
                vals["name"] = ln
            else:
                vals["name"] = vals.get("mobile", False)

        return super(ResPartner, self).create(vals)

    def write(self, vals):
        # ── SA ID validation ───────────────────────────────────────────────
        if vals.get("sa_id"):
            if not self.validate_rsa_id_number(vals["sa_id"]):
                raise ValidationError("Invalid RSA ID Number.")
            vals["is_rsa_id_valid"] = True
            if (
                self.search_count(
                    [("sa_id", "=", vals["sa_id"]), ("id", "!=", self.id)]
                )
                > 0
            ):
                raise ValidationError("Duplicate ID Number not permitted.")

        # ── Passport ───────────────────────────────────────────────────────
        if vals.get("passport"):
            vals["passport"] = vals["passport"].upper()
            if (
                self.search_count(
                    [
                        ("passport", "=", vals["passport"]),
                        ("id", "!=", self.id),
                    ]
                )
                > 0
            ):
                raise ValidationError("Duplicate Passport not permitted")

        # ── Mobile formatting + duplicate check ────────────────────────────
        if format_msisdn and MSISDNFormat:
            _logger.info(
                f"Writing SF partner {self.name} ({self.sales_force_code}) "
                f"with vals: {vals}"
            )
            for field in ("mobile", "mobile_2", "phone"):
                if vals.get(field):
                    formatted = format_msisdn(vals[field], MSISDNFormat.E164.value)
                    if formatted:
                        formatted = formatted[1:]
                        vals[field] = formatted
                        dup = self.env["res.partner"].search_count(
                            [
                                "|",
                                "|",
                                ("mobile", "=", formatted),
                                ("mobile_2", "=", formatted),
                                ("phone", "=", formatted),
                                ("customer", "!=", True),
                                ("id", "!=", self.id),
                            ]
                        )
                        if dup > 0:
                            raise ValidationError(
                                f"Duplicate mobile number for field {field}, "
                                f"value {formatted}. "
                                f"SF partner {self.name} ({self.sales_force_code}) "
                                f"has this mobile number."
                            )
                    else:
                        raise ValidationError(
                            f"Invalid mobile number for field {field}"
                        )

        # ── Name construction from first_name / last_name ──────────────────
        if not vals.get("name"):
            fn = vals.get("first_name")
            ln = vals.get("last_name")
            if fn and ln:
                vals["name"] = f"{fn} {ln}"
            elif fn and not ln and self.last_name:
                vals["name"] = f"{fn} {self.last_name}"
            elif ln and not fn and self.first_name:
                vals["name"] = f"{self.first_name} {ln}"
            elif fn:
                vals["name"] = fn
            elif ln:
                vals["name"] = ln

        res = super(ResPartner, self).write(vals)

        # ── Outbound sync (source: bbb_sales_force_genealogy) ─────────────
        if res and not self.env.context.get("source_sync", False):
            mapped_fields = self.env["sf.mapping.field"].search(
                [("local_model_name", "=", self._name), ("outbound", "=", True)]
            )
            sync_vals = {}
            for field in mapped_fields:
                if field.local_field_name in vals:
                    sync_vals[field.local_field_name] = vals.get(
                        field.local_field_name
                    )

            _logger.info(
                f"Write: {vals} | Mapped: {mapped_fields} | Sync: {sync_vals}"
            )

            if sync_vals and self.remote_id:
                self.sync_outbound("res_partner", self.id, "update", sync_vals)
                self.write({"last_outbound_sync_date": dt.now()})

        return res

    # ─────────────────────────────────────────────────────────────────────────
    # Outbound sync helper  (source: bbb_sales_force_genealogy)
    #   config params renamed: bbb_sales_force_genealogy.* → sales_force_support.*
    # ─────────────────────────────────────────────────────────────────────────

    def sync_outbound(self, model_name, record_id, method="update", sync_vals=None):
        if sync_vals is None:
            sync_vals = {}
        ir_config = self.env["ir.config_parameter"]
        sync_enabled = ir_config.get_param(
            "sales_force_support.enable_outbound_synchronisation", default=False
        )
        if not sync_enabled:
            _logger.warning("Outbound synchronisation is disabled")
            return

        sync_url = ir_config.get_param("sales_force_support.outbound_url", default=False)
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
            _logger.warning("Outbound synchronisation is not fully configured")
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
            if not session_id:
                _logger.error(
                    "Failed to retrieve session ID from authentication response"
                )
                return

            headers["X-Openerp"] = f"session_id={session_id}"
            headers["Cookie"] = f"session_id={session_id}"

            sync_vals["id"] = record_id
            sync_vals["name"] = self.browse([record_id]).name
            payload = {"jsonrpc": "2.0", "params": sync_vals}

            try:
                if method == "create":
                    endpoint = f"{sync_url}/sales_force/{model_name}"
                    resp = requests.post(
                        url=endpoint, data=json.dumps(payload), headers=headers
                    )
                    resp.raise_for_status()
                    if resp.json().get("result", {}).get("id"):
                        remote_id = resp.json()["result"]["id"]
                        self.browse([record_id]).write({"remote_id": remote_id})
                elif method == "update":
                    endpoint = f"{sync_url}/sales_force/{model_name}/{self.id}"
                    resp = requests.post(
                        url=endpoint, data=json.dumps(payload), headers=headers
                    )
                    resp.raise_for_status()
                elif method == "archive":
                    endpoint = f"{sync_url}/sales_force/{model_name}/archive"
                    resp = requests.post(
                        url=endpoint, data=json.dumps(payload), headers=headers
                    )
                    resp.raise_for_status()
            except Exception as e:
                _logger.error(f"Failed to sync record: {str(e)}")
                return

        except Exception:
            _logger.error(
                "Failed to retrieve session ID from authentication response"
            )
            return

    # ─────────────────────────────────────────────────────────────────────────
    # Compuscan CheckScore  (source: partner_compuscan/models/res_partner.py)
    # ─────────────────────────────────────────────────────────────────────────

    def add_compuscan_log(self, level="Error", line="-", message=""):
        self.env["ir.logging"].sudo().create(
            {
                "dbname": self.env.cr.dbname,
                "name": "Compuscan - Get Score",
                "type": "server",
                "func": "_get_compuscan_checkscore_data",
                "path": (
                    f"[({self.env.user.id}, {self.env.user.name}), "
                    f"({self.id}, {self.name})]"
                ),
                "line": line,
                "level": level,
                "message": message,
            }
        )

    @property
    def _get_compuscan_checkscore_data(self):
        self.ensure_one()
        _logger.info(f"(_get_compuscan_checkscore_data: {self.sa_id})")

        success_logs = self.env["ir.logging"].search(
            [
                ("func", "=", "_get_compuscan_checkscore_data"),
                ("line", "=", self.sa_id),
                ("level", "=", "Info"),
                ("message", "like", "%Success%"),
            ]
        )
        if success_logs:
            return None

        error_logs = self.env["ir.logging"].search(
            [
                "&",
                "&",
                "&",
                ("func", "=", "_get_compuscan_checkscore_data"),
                ("line", "=", self.sa_id),
                ("level", "=", "Error"),
                "|",
                ("message", "like", "%Exception%"),
                ("message", "like", "%Error%"),
            ],
            order="create_date desc",
        )

        if error_logs and len(error_logs) < 3:
            last_call = error_logs[0]
            if (
                datetime.datetime.now() - last_call.create_date
            ).total_seconds() < 300:
                return None
        elif error_logs and len(error_logs) >= 3:
            self.env["mail.mail"].create(
                {
                    "subject": "Compuscan CheckScore API Error Alert",
                    "body_html": (
                        f"<p>The Compuscan CheckScore service has reached 3 retries "
                        f"for partner: {self.name} (ID: {self.sa_id}, "
                        f"Mobile: {self.mobile})</p>"
                    ),
                    "email_to": "ict@bbb.co.za",
                    "email_from": "ict-support@bbb.co.za",
                }
            ).send()
            return None

        url = "https://apis.experian.co.za:9443/PersonScoreService/getScore/"
        if self.env.company.compuscan_env != "prod":
            url = "https://apis-uat.experian.co.za:9443/KycService/getScore/"

        user, passwd = self.env.company._get_compuscan_credentials()

        params = {
            "pUsername": user,
            "pPassword": passwd,
            "pIdNumber": self.sa_id,
            "pResultType": "json",
            "pMyOrigin": "Odoo/17.0 sales_force_support/1.0.0",
            "pVersion": "1.0",
        }
        try:
            resp = requests.post(
                url,
                params=params,
                headers={"User-Agent": "Odoo/17.0 sales_force_support/1.0.0"},
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.add_compuscan_log(
                line=self.sa_id,
                message=f"Payload: {params}\n\nError: {str(e.response.text)}",
            )
            return None
        except Exception as e:
            self.add_compuscan_log(
                line=self.sa_id,
                message=f"Payload: {params}\n\nException: {str(e)}",
            )
            return None

        data = resp.json()
        if not data:
            self.add_compuscan_log(
                line=self.sa_id,
                message=f"Payload: {params}\n\nError: {str(resp)}",
            )
            return None

        if data.get("transactionCompleted") is False and data.get("errorCode") == "-115":
            self.add_compuscan_log(
                line=self.sa_id, message=f"Payload: {params}\n\nError: {data}"
            )
            return None

        try:
            result = json.loads(data["returnData"])
        except Exception as e:
            self.add_compuscan_log(
                line=self.sa_id, message=f"Payload: {params}\n\nException: {str(e)}"
            )
            return None

        self.add_compuscan_log(
            line=self.sa_id,
            level="Info",
            message=f"Params: {params}\n\nSuccess:\n\n{result}",
        )
        return result

    def button_compuscan_checkscore(self):
        self.ensure_one()
        try:
            data = self._get_compuscan_checkscore_data
            if not data:
                return
        except Exception:
            if self.env.context.get("compuscan_ignore_errors"):
                return
            raise

        checkscore_cpa = checkscore_nlr = False
        checkscore_other = []
        for score in data["results"]:
            score_type = score["resultType"]
            score_decision = score["score"]

            if score_type == "CPA":
                checkscore_cpa = score_decision
                self.compuscan_checkscore_cpa = score_decision
            elif score_type == "NLR":
                checkscore_nlr = score_decision
                self.compuscan_checkscore_nlr = score_decision
            else:
                checkscore_other.append((score_type, score_decision))
                _logger.warning(
                    "Compuscan CheckScore returned unknown score type '%s' "
                    "with decision '%s'",
                    score_type,
                    score_decision,
                )

        self.with_context(mail_notrack=True).write(
            {
                "compuscan_checkscore_risk": "unknown",
                "compuscan_checkscore_date": fields.Datetime.now(),
            }
        )

        body = "<p>A Compuscan CreditScore check was processed:</p>\n<ul>\n"
        if checkscore_cpa:
            body += f"\t<li><strong>CPA Score:</strong> {checkscore_cpa}</li>\n"
        if checkscore_nlr:
            body += f"\t<li><strong>NLR Score:</strong> {checkscore_nlr}</li>\n</ul>\n"
        if checkscore_other:
            body += (
                "<p>Other unknown score types were also returned but ignored:</p>\n<ul>\n"
            )
            for st, sd in checkscore_other:
                body += f"\t<li><strong>{st} Score:</strong> {sd}</li>\n"
            body += "</ul>\n"
        body += "<p>The credit status was judged to be <strong>unknown</strong></p>"
        if self.env.company.compuscan_env != "prod":
            body += "\n<em>This request was executed with the sandbox environment.</em>"

        self.message_post(body=body, body_is_html=True)

    # ─────────────────────────────────────────────────────────────────────────
    # ConsumerView KYC  (source: partner_consumerview/models/res_partner.py)
    # ─────────────────────────────────────────────────────────────────────────

    def add_consumerview_log(self, level="Error", line="-", message=""):
        self.env["ir.logging"].sudo().create(
            {
                "dbname": self.env.cr.dbname,
                "name": "Consumerview - Get Basic Info",
                "type": "server",
                "func": "_get_consumerview_data",
                "path": (
                    f"[({self.env.user.id}, {self.env.user.name}), "
                    f"({self.id}, {self.name})]"
                ),
                "line": line,
                "level": level,
                "message": message,
            }
        )

    def _get_google_maps_address_details(
        self, street=None, suburb=None, city=None, zip=None
    ):
        apikey = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base_geolocalize.google_map_api_key")
        )
        address_list = [
            street,
            suburb,
            ("%s %s" % (zip or "", city or "")).strip(),
        ]
        address_list = [item for item in address_list if item]
        address_string = ", ".join(address_list)

        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "sensor": "false",
            "address": address_string,
            "components": "country:za|ls|bw|sz|zw|mz",
            "key": apikey,
        }

        try:
            result_json = requests.get(url, params).json()
            if result_json.get("status") != "OK":
                return False

            address_components = result_json["results"][0]["address_components"]
            verified_address = {}
            for component in address_components:
                comp_type = component["types"]
                if "country" in comp_type:
                    country_id = self.env["res.country"].search(
                        [("name", "=", component["long_name"])], limit=1
                    )
                    if country_id:
                        verified_address["country_id"] = country_id.id
                elif "administrative_area_level_1" in comp_type:
                    state_id = self.env["res.country.state"].search(
                        [("name", "=", component["long_name"])], limit=1
                    )
                    if state_id:
                        verified_address["state_id"] = state_id.id
                elif "locality" in comp_type:
                    verified_address["city"] = component["long_name"]
                elif "sublocality" in comp_type:
                    verified_address["suburb"] = component["long_name"]
                elif "postal_code" in comp_type:
                    verified_address["zip"] = component["long_name"]

            return verified_address

        except Exception as e:
            raise UserError(
                _("GoogleMaps Geocode returned an error:\n\n%s") % (str(e))
            )

    def _get_consumerview_data(
        self, id_number="-", mobile="-", email="-", id_type="SID"
    ):
        self.ensure_one()
        _logger.info(f"(_get_consumerview_data: {id_number})")

        success_logs = self.env["ir.logging"].search(
            [
                ("func", "=", "_get_consumerview_data"),
                ("line", "=", id_number),
                ("level", "=", "Info"),
                ("message", "like", "%Success%"),
            ]
        )
        if success_logs:
            return None

        error_logs = self.env["ir.logging"].search(
            [
                "&",
                "&",
                "&",
                ("func", "=", "_get_consumerview_data"),
                ("line", "=", id_number),
                ("level", "=", "Error"),
                "|",
                ("message", "like", "%Exception%"),
                ("message", "like", "%Error%"),
            ],
            order="create_date desc",
        )

        if error_logs and len(error_logs) < 3:
            last_call = error_logs[0]
            if (
                datetime.datetime.now() - last_call.create_date
            ).total_seconds() < 300:
                return None
        elif error_logs and len(error_logs) >= 3:
            self.env["mail.mail"].create(
                {
                    "subject": "ConsumerView API Error Alert",
                    "body_html": (
                        f"<p>The ConsumerView service has reached 3 retries "
                        f"for partner: {self.name} (ID: {id_number}, "
                        f"Mobile: {self.mobile})</p>"
                    ),
                    "email_to": "ict@bbb.co.za",
                    "email_from": "ict-support@bbb.co.za",
                }
            ).send()
            return None

        # Ping server
        ping_url = "https://apis.experian.co.za:9443/KycService/PingServer"
        if self.env.company.compuscan_env != "prod":
            ping_url = "https://apis-uat.experian.co.za:9443/KycService/PingServer"

        response = requests.get(url=ping_url)
        if not response or response.status_code != 200:
            self.add_consumerview_log(
                line=id_number,
                message=f"ConsumerView server not available: {str(response)}",
            )
            return None

        url = "https://apis.experian.co.za:9443/KycService/RequestNewKYC"
        if self.env.company.compuscan_env != "prod":
            url = "https://apis-uat.experian.co.za:9443/KycService/RequestNewKYC"

        headers = {
            "content-type": "application/json",
            "User-Agent": "Odoo/17.0 sales_force_support/1.0.0",
        }
        user, passwd = self.env.company._get_consumerview_credentials()
        payload = {
            "auth": {
                "username": user,
                "password": passwd,
                "version": "1.0",
                "origin": "SOAP_UI",
            },
            "search_criteria": {
                "identity_number": id_number,
                "identity_type": id_type,
                "forename": "",
                "surname": "",
                "want_sources": "N",
                "want_pdf": "N",
                "want_idv_service": "N",
                "want_search_criteria": "N",
                "want_addresses": "Y",
                "want_employment": "N",
                "want_contact": "N",
                "want_safps": "N",
                "want_email": "N",
                "want_judgements": "N",
                "want_notices": "N",
            },
        }

        try:
            resp = requests.post(
                url=url, data=json.dumps(payload), headers=headers
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.add_consumerview_log(
                line=id_number,
                message=f"Payload: {payload}\n\nError: {e.response.text}",
            )
            return None
        except Exception as e:
            self.add_consumerview_log(
                line=id_number,
                message=f"Payload: {payload}\n\nException: {str(e)}",
            )
            return None

        data = resp.json()
        if not data:
            self.add_consumerview_log(
                line=id_number, message=f"Payload: {payload}\n\nError: {str(resp)}"
            )
            return None

        if data.get("response_status") != "Success":
            self.add_consumerview_log(
                line=id_number, message=f"Payload: {payload}\n\nError: {data}"
            )
            return None

        self.add_consumerview_log(
            line=id_number,
            level="Info",
            message=f"Payload: {payload}\n\nSuccess: {data}",
        )
        return data

    def button_consumerview_populate(self):
        self.ensure_one()

        id_number = self.sa_id or "-"
        passport_number = self.passport or "-"

        data = False
        try:
            if id_number != "-":
                data = self._get_consumerview_data(
                    id_number=id_number, id_type="SID"
                )
            elif passport_number != "-":
                data = self._get_consumerview_data(
                    id_number=passport_number, id_type="PASSPORT"
                )
        except Exception as e:
            if self.env.context.get("consumerview_ignore_errors", False):
                return
            raise ValidationError(
                _("ConsumerView Error:\n\n%s") % (str(e))
            )

        if not data:
            return False

        return_data = data["return_data"]
        person_found = return_data["stats"]["person_found"]

        if person_found != "Y":
            if self.env.context.get("consumerview_raise_not_found", True):
                return True
            return True

        if not (
            return_data["stats"].get("address_count")
            and return_data["stats"]["address_count"] > 0
        ):
            return True

        # Determine first/last name
        first_name = last_name = name = None
        ddm = return_data.get("definite_match_data") or {}
        if ddm.get("forename_1"):
            first_name = ddm["forename_1"]
            name = str(first_name)
        if ddm.get("surname") and first_name:
            last_name = ddm["surname"]
            name = f"{first_name} {last_name}"

        # Pick latest address
        address_count = return_data["stats"]["address_count"]
        latest_date = datetime.datetime.strptime(
            return_data["address_data"][0]["first_date_created"], "%Y-%m-%d"
        )
        last_address_index = 0
        for ind in range(address_count):
            addr_date = datetime.datetime.strptime(
                return_data["address_data"][ind]["first_date_created"], "%Y-%m-%d"
            )
            if addr_date > latest_date:
                latest_date = addr_date
                last_address_index = ind

        addr = return_data["address_data"][last_address_index]
        street = addr.get("line_1") or False
        suburb = addr.get("line_2") or False
        city = addr.get("line_3") or False
        zip_code = addr.get("postal_code") or False

        line_vals_dict = {
            "name": name,
            "first_name": first_name,
            "last_name": last_name,
            "street": street,
            "street2": False,
            "suburb": suburb,
            "city": city,
            "zip": zip_code,
            "state_id": False,
            "opt_out": False,
        }

        verified_address = self._get_google_maps_address_details(
            street=street, suburb=suburb, city=city, zip=zip_code
        )
        if verified_address:
            for field in ["street", "street2", "suburb", "city", "zip", "state_id"]:
                if field in verified_address:
                    line_vals_dict[field] = verified_address[field]

        line_vals = [(0, 0, line_vals_dict)]
        external_id = return_data.get("enquiry_id") or False

        resolve = self.env["partner.consumerview.resolve"].create(
            {
                "partner_id": self.id,
                "ref": external_id,
                "line_ids": line_vals,
            }
        )

        if self.env.context.get("consumerview_pick_first") or len(line_vals) == 1:
            resolve.chosen_line_id = resolve.line_ids[0]
            resolve.action_choose()
        else:
            return {
                "type": "ir.actions.act_window",
                "name": _("ConsumerView"),
                "res_model": "partner.consumerview.resolve",
                "res_id": resolve.id,
                "view_mode": "form",
                "view_type": "form",
                "target": "new",
            }
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Geospatial consultant allocation  (source: bb_allocate/models/res_partner.py)
    #   hr.employee → sf.member  |  hr_employee table → sf_member table
    #   job_id.name → genealogy
    # ─────────────────────────────────────────────────────────────────────────

    def _get_nearby(self, domain=None, distance=None, order=None, limit=None):
        self.ensure_one()

        partner = self

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
            for *res_id, distance in id_distances:
                yield self.browse([res_id[0]]), distance

            id_distances = self.env.cr.fetchmany(100)

    def button_allocate_consultant(self):
        for partner in self:
            partner.geo_localize()

        for partner in self:
            domain = [("genealogy", "in", ("Consultant", "Prospective Manager"))]

            if partner.manager_id and partner.consultant_blacklist:
                self.consultant_blacklist += ",%s" % partner.consultant_id.id
            elif partner.manager_id:
                self.consultant_blacklist = str(partner.consultant_id.id)

            if self.consultant_blacklist:
                domain.append(
                    ("id", "not in", self.consultant_blacklist.split(","))
                )

            if partner.state_id:
                state_domain_term = ("state_id", "=", partner.state_id.id)
                domain.append(state_domain_term)

            if partner.country_id:
                country_domain_term = ("country_id", "=", partner.country_id.id)
                domain.append(country_domain_term)
            else:
                raise UserError(_("Customer address is not set"))

            order = "h.four_months_sales DESC, distance"

            if partner.partner_longitude and partner.partner_latitude:
                distance = 1.0

                lon_min = ("partner_id.partner_longitude", ">=",
                           partner.partner_longitude - distance)
                lon_max = ("partner_id.partner_longitude", "<=",
                           partner.partner_longitude + distance)
                lat_min = ("partner_id.partner_latitude", ">=",
                           partner.partner_latitude - distance)
                lat_max = ("partner_id.partner_latitude", "<=",
                           partner.partner_latitude + distance)

                domain.extend([lon_min, lon_max, lat_min, lat_max])

                employees = [
                    p.id
                    for p, d in self._get_nearby(domain, distance, order=order)
                ]

                for term in [lon_min, lon_max, lat_min, lat_max]:
                    domain.remove(term)
            else:
                employees = False

            order = "four_months_sales DESC"

            if not employees and partner.city:
                city_domain_term = ("city", "=", partner.city)
                domain.append(city_domain_term)
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(city_domain_term)

            if not employees and partner.state_id:
                employees = self.env["sf.member"].search(domain, order=order)
                domain.remove(state_domain_term)

            if not employees:
                employees = self.env["sf.member"].search(domain, order=order)

            if employees:
                partner.consultant_id = employees[0]
            else:
                raise UserError(_("Could not find a consultant nearby"))

