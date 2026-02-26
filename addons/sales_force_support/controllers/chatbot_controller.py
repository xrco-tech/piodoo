# Source: bb_chatbot/controllers/main.py
from werkzeug.exceptions import BadRequest, MethodNotAllowed, NotFound, Unauthorized

import hashlib

from odoo import api, http, SUPERUSER_ID, _
from odoo import registry as registry_get
from odoo.exceptions import UserError
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

# from odoo.addons.web.controllers.main import db_monodb


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

DEFAULT_EMPLOYEE_FIELDS = [
    "id",
    "sales_force_code",
    "name",
    "first_name",
    "last_name",
    "mobile",
    "related_distributor_id",
    "manager_id",
    "view_model",
    "view_res_id",
]
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

WHITELISTED_WRITE_APPLICANT_FIELDS = [
    "name",
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
    "manager_id",
    "is_credit_check",
    "recruiter_id",
    "gender",
    "birth_date",
    "address_verified",
    "compuscan_checkscore_cpa",
    "compuscan_checkscore_nlr",
    "compuscan_checkscore_date",
    "credit_score",
    "recruiter_source",
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

WHITELISTED_CREATE_APPLICANT_FIELDS = WHITELISTED_WRITE_APPLICANT_FIELDS
WHITELISTED_READ_APPLICANT_FIELDS = (
    WHITELISTED_WRITE_APPLICANT_FIELDS
    + DEFAULT_APPLICANT_FIELDS
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

ALLOWED_METHODS = [
    "read",
    "write",
    "search",
    "create",
    "create_customer",
    "create_employee",
    "compuscan",
    "consumerview",
    "allocate_manager",
    "allocate_consultant",
    "archive",
    "unarchive",
]

PARTNER_TO_EMPLOYEE_FIELD_VALUES = [
    "consultant_id",
    "recruiter_id",
    "manager_id",
    "distributor_id",
]

NAME_TO_ID_FIELD_VALUES = {
    "stage_id": "sf.recruit.stage",
    "state_id": "res.country.state",
    "country_id": "res.country",
}


class BbChatbotController(http.Controller):
    @http.route(
        [
            "/bb_chatbot/partner/<method>",
            "/bb_chatbot/partner/<method>/<int:partner_id>",
        ],
        type="http",
        auth="none",
        csrf=False,
    )
    def partner(self, method, partner_id=None, **data):
        dbname = data.pop("db", None)
        if not dbname:
            # Applified Developer : Comment Start, For Old Code, db_monodb() no longer supported => Issue #114, Review - Applified Review Doc File for detailed review
            dbname = request.db
        if not dbname:
            return BadRequest()
        if not http.db_filter([dbname]):
            return BadRequest()
        auth = request.httprequest.headers.get("Authorization")

        if not auth:
            token = data.get("token")
            if not token:
                return Unauthorized()
        else:
            token_type, token = auth.split()
            if token_type not in ("Bearer", "Token"):
                raise Unauthorized()
        hashed_token = hashlib.sha512(token.encode("utf-8", errors="ignore"))

        registry = registry_get(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            user = (
                env["res.users"]
                .with_context(active_test=False)
                .search([("chatbot_access_token", "=", hashed_token.hexdigest())])
            )

            if not user:
                return Unauthorized()
            uid = user.id
            env = api.Environment(cr, uid, {})
            if method not in ALLOWED_METHODS:
                raise BadRequest(_("Unknown method: %s") % method)

            fields = data.get("fields")
            fields = fields and fields.split(",")
            partners = []
            if partner_id:
                partners = env["res.partner"].browse([partner_id])
            elif method == "search":
                if "id_number" in data:
                    domain = [
                        "|",
                        ("sa_id", "=", data["id_number"]),
                        ("passport", "=", data["id_number"]),
                    ]
                elif "sa_id" in data:
                    domain = [("sa_id", "=", data["sa_id"])]
                elif "passport" in data:
                    domain = [("passport", "=", data["passport"])]
                elif "mobile" in data:
                    domain = [
                        "|",
                        ("mobile", "=", data["mobile"]),
                        ("mobile", "=", "+" + data["mobile"]),
                    ]
                elif "sales_force_code" in data:
                    domain = [("sales_force_code", "=", data["sales_force_code"])]
                else:
                    return BadRequest(
                        _(
                            "You must specify a mobile number, ID number or Sale Force Code"
                        )
                    )
                if data.get("inactive"):
                    domain.append(("active", "=", False))

                partners = env["res.partner"].search(domain, order="id")

            elif method not in (
                "create",
                "create_applicant",
                "create_customer",
                "create_employee",
            ):
                return NotFound(
                    _("Please specify a partner ID in your URL for this method")
                )
            if (
                method
                not in (
                    "create",
                    "create_applicant",
                    "create_customer",
                    "unarchive",
                    "create_employee",
                )
                and not partners
            ):
                return NotFound(_("Partner not found"))

            results = []
            if method == "create_customer":
                vals = {}
                for field, value in data.items():
                    if field in ("token", "fields"):
                        continue
                    elif field not in WHITELISTED_CREATE_PARTNER_FIELDS:
                        return BadRequest(
                            _("Attempted to create with a non-whitelisted field: %s")
                            % field
                        )
                    elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                        value = env["sf.member"].search([("partner_id", "=", value)])
                        value = value and value.id or False
                    elif field in NAME_TO_ID_FIELD_VALUES and value:
                        value = NAME_TO_ID_FIELD_VALUES[field].search(
                            [("name", "=", value)], limit=1
                        )
                        value = value and value.id or False
                    elif field in NAME_TO_ID_FIELD_VALUES:
                        value = False
                    vals[field] = value

                vals["customer"] = True
                partners = env["res.partner"].create(vals)
            elif method in ("create", "create_applicant"):
                return self._applicant(env, method, **data)
            elif method == "create_employee":
                return self._create_employee(env, method, **data)
            elif method == "unarchive":
                env["sf.member"].search(
                    [("active", "=", False), ("partner_id", "=", partner_id)]
                ).write({"active": True})
                env["sf.recruit"].search(
                    [("active", "=", False), ("partner_id", "=", partner_id)]
                ).write({"active": True})
                env["res.partner"].search(
                    [("active", "=", False), ("id", "=", partner_id)]
                ).write({"active": True})
                return True

            # pass employee (consultant/manager/distributor) and applicant (potential recruit) to another method
            for partner in partners:
                if partner and partner.view_model == "sf.member":
                    results.append(
                        self._employee(env, method, partner.view_res_id, **data)
                    )
                    continue
                elif partner and partner.view_model == "sf.recruit":
                    results.append(
                        self._applicant(env, method, partner.view_res_id, **data)
                    )
                    continue

                if not fields:
                    fields = DEFAULT_PARTNER_FIELDS.copy()
                if method == "archive":
                    partner.active = False
                    return True
                elif method == "consumerview":
                    context = {
                        "consumerview_pick_first": True,
                        "consumerview_ignore_errors": False,
                        "consumerview_raise_not_found": True,
                    }
                    partner.with_context(**context).button_consumerview_populate()
                    if not fields:
                        fields = DEFAULT_PARTNER_FIELDS + [
                            "unverified_first_name",
                            "unverified_last_name",
                            "unverified_street",
                            "unverified_suburb",
                            "unverified_city",
                            "unverified_state_id",
                            "unverified_country_id",
                            "unverified_zip",
                        ]

                elif method == "allocate_consultant":
                    partner.button_allocate_consultant()
                    if not fields:
                        fields = DEFAULT_PARTNER_FIELDS + ["consultant_id"]
                elif method == "allocate_manager":
                    return BadRequest(_("Cannot allocate a manager to a customer"))
                elif method == "write":
                    vals = {}
                    for field, value in data.items():
                        if field in ("token", "fields"):
                            continue
                        elif field not in WHITELISTED_WRITE_PARTNER_FIELDS:
                            return BadRequest(
                                _("Attempted to write a non-whitelisted field: %s")
                                % field
                            )
                        elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                            value = env["sf.member"].search(
                                [("partner_id", "=", value)]
                            )
                            value = value and value.id or False
                        elif field in NAME_TO_ID_FIELD_VALUES and value:
                            value = env[NAME_TO_ID_FIELD_VALUES[field]].search(
                                [("name", "=", value)], limit=1
                            )
                            value = value and value.id or False
                        elif field in NAME_TO_ID_FIELD_VALUES:
                            value = False
                        vals[field] = value
                    partner.write(vals)

                res = {}
                res_ = partner.read(fields=fields)[0]
                for field, value in res_.items():
                    if field in PARTNER_TO_EMPLOYEE_FIELD_VALUES and value:
                        res_id, name = value
                        partner_id = env["sf.member"].browse(res_id).partner_id.id
                        value = [partner_id, name]
                    elif field not in WHITELISTED_READ_PARTNER_FIELDS:
                        return BadRequest(
                            _("Attempted to read a non-whitelisted field: %s") % field
                        )

                    res[field] = value
                results.append(res)

            if len(partners) == 1 and method != "search":
                return results[0]

            return results

    def _employee(self, env, method, employee_id, **data):
        employee = env["sf.member"].browse([employee_id])

        fields = data.get("fields")
        fields = fields and fields.split(",")

        if method == "archive":
            employee.partner_id.active = False
            employee.active = False
            return True
        elif method == "consumerview":
            context = {
                "consumerview_pick_first": True,
                "consumerview_ignore_errors": False,
                "consumerview_raise_not_found": True,
            }

            employee.with_context(**context).button_consumerview_populate()

            if not fields:
                fields = DEFAULT_EMPLOYEE_FIELDS + [
                    "unverified_first_name",
                    "unverified_last_name",
                    "unverified_street",
                    "unverified_suburb",
                    "unverified_city",
                    "unverified_state_id",
                    "unverified_country_id",
                    "unverified_zip",
                ]
        elif method == "compuscan":
            context = {"compuscan_ignore_errors": True}
            employee.with_context(**context).button_compuscan_checkscore()
            if not fields:
                fields = DEFAULT_EMPLOYEE_FIELDS + [
                    "compuscan_checkscore_cpa",
                    "compuscan_checkscore_nlr",
                    "credit_score",
                    "compuscan_checkscore_date",
                ]
        elif method == "allocate_consultant":
            return BadRequest(
                _("Cannot allocate a consultant to another consultant, only a customer")
            )
        elif method == "allocate_manager":
            employee.button_allocate_manager()
            if not fields:
                fields = DEFAULT_EMPLOYEE_FIELDS + ["manager_id"]
        elif method == "write":
            vals = {}

            for field, value in data.items():
                if field in ("token", "fields"):
                    continue
                elif field not in WHITELISTED_WRITE_EMPLOYEE_FIELDS:
                    return BadRequest(
                        _("Attempted to write a non-whitelisted field: %s") % field
                    )
                elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                    value = env["sf.member"].search([("partner_id", "=", value)])
                    value = value and value.id or False
                elif field in NAME_TO_ID_FIELD_VALUES and value:
                    value = env[NAME_TO_ID_FIELD_VALUES[field]].search(
                        [("name", "=", value)], limit=1
                    )
                    value = value and value.id or False
                elif field in NAME_TO_ID_FIELD_VALUES:
                    value = False

                vals[field] = value

            if not fields:
                fields = ["id"] + list(vals.keys())

            employee.write(vals)

        if not fields:
            fields = DEFAULT_EMPLOYEE_FIELDS.copy()

        try:
            fields.remove("view_model")
            view_model = True
        except ValueError:
            view_model = False

        try:
            fields.remove("view_res_id")
            view_res_id = True
        except ValueError:
            view_res_id = False

        res = {}
        res_ = employee.read(fields=fields)[0]
        for field, value in res_.items():
            if field in PARTNER_TO_EMPLOYEE_FIELD_VALUES and value:
                res_id, name = value
                partner_id = env["sf.member"].browse(res_id).partner_id.id
                value = [partner_id, name]
            elif field not in WHITELISTED_READ_EMPLOYEE_FIELDS:
                return BadRequest(
                    _("Attempted to read a non-whitelisted field: %s") % field
                )
            elif field in NAME_TO_ID_FIELD_VALUES and value:
                res_id, name = value
                value = name

            res[field] = value

        if view_model:
            res["view_model"] = "sf.member"
        if view_res_id:
            res["view_res_id"] = res["id"]

        res["id"] = employee.partner_id.id

        return res

    def _applicant(self, env, method, applicant_id=None, **data):
        if applicant_id:
            applicant = env["sf.recruit"].browse([applicant_id])

        fields = data.get("fields")
        fields = fields and fields.split(",")

        if method == "archive":
            applicant.partner_id.active = False
            applicant.active = False
        elif method == "consumerview":
            context = {
                "consumerview_pick_first": True,
                "consumerview_ignore_errors": False,
                "consumerview_raise_not_found": True,
            }

            applicant.with_context(**context).button_consumerview_populate()

            if not fields:
                fields = DEFAULT_APPLICANT_FIELDS + [
                    "unverified_first_name",
                    "unverified_last_name",
                    "unverified_street",
                    "unverified_suburb",
                    "unverified_city",
                    "unverified_state_id",
                    "unverified_country_id",
                    "unverified_zip",
                ]
        elif method == "compuscan":
            context = {"compuscan_ignore_errors": True}
            applicant.with_context(**context).button_compuscan_checkscore()
            if not fields:
                fields = DEFAULT_APPLICANT_FIELDS + [
                    "compuscan_checkscore_cpa",
                    "compuscan_checkscore_nlr",
                    "credit_score",
                    "compuscan_checkscore_date",
                ]
        elif method == "allocate_consultant":
            return BadRequest(
                _("Cannot allocate a consultant to another recruit, only a customer")
            )
        elif method == "allocate_manager":
            applicant.button_allocate_manager()
            if not fields:
                fields = DEFAULT_APPLICANT_FIELDS + ["manager_id"]
        elif method == "write":
            vals = {}

            for field, value in data.items():
                if field in ("token", "fields"):
                    continue
                elif field not in WHITELISTED_WRITE_APPLICANT_FIELDS:
                    return BadRequest(
                        _("Attempted to write a non-whitelisted field: %s") % field
                    )
                elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                    value = env["sf.member"].search([("partner_id", "=", value)])
                    value = value and value.id or False
                elif field in NAME_TO_ID_FIELD_VALUES and value:
                    new_value = env[NAME_TO_ID_FIELD_VALUES[field]].search(
                        [("name", "=", value)], limit=1
                    )
                    if not new_value:
                        return BadRequest(
                            _("Could not find value for '%s' on fields '%s'")
                            % (field, value)
                        )
                    value = new_value.id
                elif field in NAME_TO_ID_FIELD_VALUES:
                    value = False

                if (
                    vals.get("first_name", applicant.first_name)
                    and vals.get("last_name", applicant.last_name)
                    and vals.get("street", applicant.street)
                    and vals.get("city", applicant.city)
                    and vals.get("state_id", applicant.state_id)
                ):
                    vals["address_verified"] = True

                vals[field] = value

            applicant.write(vals)

            if not fields:
                fields = ["id"] + list(vals.keys())
        elif method in ("create", "create_applicant"):
            vals = {}
            for field, value in data.items():
                if field in ("token", "fields"):
                    continue
                elif field not in WHITELISTED_CREATE_APPLICANT_FIELDS:
                    return BadRequest(
                        _("Attempted to create with a non-whitelisted field: %s")
                        % field
                    )
                elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                    value = env["sf.member"].search([("partner_id", "=", value)])
                    value = value and value.id or False
                vals[field] = value

            if (
                vals.get("first_name")
                and vals.get("last_name")
                and vals.get("street")
                and vals.get("city")
                and vals.get("state_id")
            ):
                vals["address_verified"] = True

            applicant = env["sf.recruit"].create(vals)

        if not fields:
            fields = DEFAULT_APPLICANT_FIELDS.copy()

        try:
            fields.remove("view_model")
            view_model = True
        except ValueError:
            view_model = False

        try:
            fields.remove("view_res_id")
            view_res_id = True
        except ValueError:
            view_res_id = False

        res = {}
        res_ = applicant.read(fields=fields)[0]
        for field, value in res_.items():
            if field in PARTNER_TO_EMPLOYEE_FIELD_VALUES and value:
                res_id, name = value
                partner_id = env["sf.member"].browse(res_id).partner_id.id
                value = [partner_id, name]
            elif field not in WHITELISTED_READ_APPLICANT_FIELDS:
                return BadRequest(
                    _("Attempted to read a non-whitelisted field: %s") % field
                )
            elif field in NAME_TO_ID_FIELD_VALUES and value:
                res_id, name = value
                value = name

            res[field] = value

        if view_model:
            res["view_model"] = "sf.recruit"
        if view_res_id:
            res["view_res_id"] = res["id"]

        res["id"] = applicant.partner_id.id

        return res

    def _create_employee(self, env, method, **data):

        fields = data.get("fields")
        fields = fields and fields.split(",")

        employee = False

        if method == "create_employee":
            vals = {}
            for field, value in data.items():
                if field in ("token", "fields"):
                    continue
                elif field not in WHITELISTED_CREATE_EMPLOYEE_FIELDS:
                    return BadRequest(
                        _("Attempted to create with a non-whitelisted field: %s")
                        % field
                    )
                elif field in PARTNER_TO_EMPLOYEE_FIELD_VALUES:
                    value = env["sf.member"].search([("partner_id", "=", value)])
                    value = value and value.id or False
                elif field == "manager_sf_code":
                    field = "manager_id"
                    value = env["sf.member"].search(
                        [("sales_force_code", "=", value)]
                    )
                    value = value and value.id or False
                vals[field] = value

            if (
                vals.get("first_name")
                and vals.get("last_name")
                and vals.get("street")
                and vals.get("city")
                and vals.get("state_id")
            ):
                vals["address_verified"] = True

            employee = env["sf.member"].create(vals)

        if not fields:
            fields = DEFAULT_EMPLOYEE_FIELDS.copy()

        try:
            fields.remove("view_model")
            view_model = True
        except ValueError:
            view_model = False

        try:
            fields.remove("view_res_id")
            view_res_id = True
        except ValueError:
            view_res_id = False

        res = {}
        if employee:
            res_ = employee.read(fields=fields)[0]
            for field, value in res_.items():
                if field in PARTNER_TO_EMPLOYEE_FIELD_VALUES and value:
                    res_id, name = value
                    partner_id = env["sf.member"].browse(res_id).partner_id.id
                    value = [partner_id, name]
                elif field not in WHITELISTED_READ_EMPLOYEE_FIELDS:
                    return BadRequest(
                        _("Attempted to read a non-whitelisted field: %s") % field
                    )
                elif field in NAME_TO_ID_FIELD_VALUES and value:
                    res_id, name = value
                    value = name

                res[field] = value

        if view_model:
            res["view_model"] = "sf.member"
        if view_res_id:
            res["view_res_id"] = res["id"]

        res["id"] = employee.partner_id.id

        return res
