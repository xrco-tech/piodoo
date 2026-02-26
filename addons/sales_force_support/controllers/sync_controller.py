# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/controllers/main.py
# Changes:
#   • config param key bbb_sales_force_genealogy.enable_inbound_synchronisation
#       → sales_force_support.enable_inbound_synchronisation
from odoo import http
from odoo.http import request
import phonenumbers
from datetime import datetime
from enum import Enum

import logging

_logger = logging.getLogger(__name__)


COUNTRY_CODES = {
    "258": "MZ",
    "263": "ZW",
    "266": "LS",
    "267": "BW",
    "265": "MW",
    "264": "NA",
    "27": "ZA",
    "268": "SZ",
    "255": "TZ",
    "260": "ZM",
    "244": "AO",
}


class MSISDNFormat(Enum):
    INTERNATIONAL = "INTERNATIONAL"
    E164 = "E164"


def format_msisdn(msisdn: str, format_: str, request_id: str = None):
    """Returns None if the msisdn is not valid, otherwise return formatted msisdn"""
    _logger.debug(
        f"in {__name__}.{format_msisdn.__qualname__}", extra={"request_id": request_id}
    )

    msisdn = msisdn.strip()
    if msisdn.startswith("+"):
        msisdn = msisdn[1:]

    msisdn_country = "ZA"
    msisdn_code = msisdn[0:3]
    if msisdn.startswith("27"):
        msisdn = msisdn[2:]
    elif msisdn_code in COUNTRY_CODES:
        msisdn_country = COUNTRY_CODES[msisdn_code]
        msisdn = msisdn[3:]

    try:
        parsed_msisdn = phonenumbers.parse(msisdn, msisdn_country)
        if phonenumbers.is_valid_number_for_region(parsed_msisdn, msisdn_country):
            if format_ == MSISDNFormat.INTERNATIONAL.value:
                msisdn = phonenumbers.format_number(
                    parsed_msisdn, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                )
            elif format_ == MSISDNFormat.E164.value:
                msisdn = phonenumbers.format_number(
                    parsed_msisdn, phonenumbers.PhoneNumberFormat.E164
                )
            else:
                raise ValueError(f"Unsupported format value provided: {format_}")
            return msisdn
        else:
            _logger.error(
                f"Parsed msisdn ({parsed_msisdn}) is invalid for region {msisdn_country}",
                extra={"request_id": request_id},
            )

    except phonenumbers.NumberParseException:
        _logger.error(
            f"NumberParseException. Country Code: {msisdn_country}. msisdn: {msisdn}",
            extra={"request_id": request_id},
        )


class SfMemberController(http.Controller):
    def _is_inbound_sync_enabled(self):
        """
        Check if inbound synchronization is enabled via configuration parameter.
        """
        ir_config = request.env["ir.config_parameter"].sudo()
        enable_sync = ir_config.get_param(
            "sales_force_support.enable_inbound_synchronisation", default=False
        )
        return enable_sync

    def validate_required_fields(self, required_fields, request_fields):
        """
        Validate if all required fields are present in kwargs.
        :param required_fields: List of required field names
        :param kwargs: Dictionary of incoming request data
        :return: List of missing fields, if any
        """
        missing_fields = [
            field for field in required_fields if field not in request_fields
        ]
        return missing_fields

    def validate_permitted_fields(self, permitted_fields, request_fields):
        """
        Validate if all the fields in the request are permitted to be updated.
        :param permitted_fields: List of fields that are allowed to be updated
        :param request_fields: List of fields from the request data (kwargs.keys())
        :return: List of invalid fields, if any
        """
        invalid_fields = [
            field for field in request_fields if field not in permitted_fields
        ]
        return invalid_fields

    @http.route("/sales_force", auth="user", csrf=False, cors="*")
    def index(self, **kw):
        return "Welcome to Sales Force Syncing API!"

    @http.route(
        "/sales_force/<string:model>", type="json", auth="user", methods=["POST"]
    )
    def create_record(self, model, **kwargs):
        model_name = model.replace("_", ".")

        _logger.info(f"Request Args: {kwargs}")

        # Check if inbound synchronization is enabled
        if not self._is_inbound_sync_enabled():
            return {
                "status": "error",
                "message": f"Inbound synchronization is disabled. Cannot create {model_name} record.",
            }

        # Check for missing fields for model
        mapped_fields = (
            request.env["sf.mapping.field"]
            .sudo()
            .search([("local_model_name", "=", model_name), ("inbound", "=", True)])
        )

        if not mapped_fields:
            return {
                "status": "error",
                "message": f"Missing configuration for {model_name} inbound synchronization.",
            }

        mapped_field_names = [field.remote_field_name for field in mapped_fields]

        disallowed_fields = self.validate_permitted_fields(mapped_field_names, kwargs)

        if disallowed_fields:
            return {
                "status": "error",
                "message": f"Field(s) {', '.join(disallowed_fields)} on {model_name} are not allowed to be synchronized.",
            }

        required_field_names = [
            field.remote_field_name
            for field in mapped_fields
            if field.required_on_create
        ]

        missing_required_fields = self.validate_required_fields(
            required_field_names, kwargs
        )

        if missing_required_fields:
            return {
                "status": "error",
                "message": f"Missing required {model_name} field(s): {', '.join(missing_required_fields)}",
            }

        non_duplicate_field_names = [
            (field.local_field_name, field.remote_field_name)
            for field in mapped_fields
            if not field.allow_duplicates
        ]

        duplicates_domain = []

        # Create a domain to check for potential duplicates
        for dupe_field in non_duplicate_field_names:
            field_name, remote_value_key = dupe_field
            field_value = kwargs.get(remote_value_key)

            if field_name in ["mobile", "phone", "mobile_connect"] and field_value:
                if format_msisdn(field_value, MSISDNFormat.E164.value):
                    formatted_number = format_msisdn(
                        field_value, MSISDNFormat.E164.value
                    )[1:]
                    field_value = formatted_number

            # Add the compound condition: field IS NOT FALSE AND field = value
            duplicates_domain += [
                "&",
                (field_name, "!=", False),
                (field_name, "=", field_value),
            ]

        # Combine all conditions with OR if there are multiple fields
        if len(non_duplicate_field_names) > 1:
            final_domain = ["|"] * (
                len(non_duplicate_field_names) - 1
            ) + duplicates_domain
        else:
            final_domain = duplicates_domain  # No need for OR if only one field

        _logger.info(f"Duplicates domain: {final_domain}")

        potential_duplicates = request.env[model_name].sudo().search(final_domain)

        _logger.info(f"Duplicate Records: {potential_duplicates}")

        if potential_duplicates:
            remote_field_names_only = [x[1] for x in non_duplicate_field_names]
            return {
                "status": "error",
                "message": f"Duplicate values on {model_name} not allowed for field(s): {', '.join(remote_field_names_only)}.",
            }

        vals = {}

        for field in mapped_fields:
            if field.remote_field_name in kwargs:

                if (
                    field.remote_field_name in ["mobile", "phone", "mobile_connect"]
                    and kwargs[field.remote_field_name]
                ):

                    if format_msisdn(
                        kwargs[field.remote_field_name], MSISDNFormat.E164.value
                    ):
                        formatted_number = format_msisdn(
                            kwargs[field.remote_field_name], MSISDNFormat.E164.value
                        )[1:]
                        kwargs[field.remote_field_name] = formatted_number

                vals[field.local_field_name] = kwargs.get(field.remote_field_name)

        _logger.info(f"Values: {vals}")

        # Create record
        try:
            context = {"source_sync": True}
            vals["last_inbound_sync_date"] = datetime.now()
            record = request.env[model_name].with_context(context).sudo().create(vals)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create {model_name}: {str(e)}",
            }

        return {
            "status": "success",
            "message": "Created successfully",
            "id": record.id,
            "vals": vals,
        }

    @http.route(
        "/sales_force/<string:model>/<int:id>",
        type="json",
        auth="user",
        methods=["PUT", "POST"],
    )
    def update_record(self, model, id, **kwargs):
        model_name = model.replace("_", ".")

        # Check if inbound synchronization is enabled
        if not self._is_inbound_sync_enabled():
            return {
                "status": "error",
                "message": f"Inbound synchronization is disabled. Cannot update {model_name} record.",
            }

        existing_record = (
            request.env[model_name].sudo().search([("remote_id", "=", id)], limit=1)
        )

        if not existing_record:
            return {
                "status": "error",
                "message": f"Record with remote_id ({id}) does not exist.",
            }

        # Check for missing fields for model
        mapped_fields = (
            request.env["sf.mapping.field"]
            .sudo()
            .search(
                [
                    ("remote_model_name", "=", model_name),
                    ("inbound", "=", True),
                    ("edit_after_create", "=", True),
                ]
            )
        )

        if not mapped_fields:
            return {
                "status": "error",
                "message": f"Missing configuration for {model_name} inbound synchronization.",
            }

        mapped_field_names = [field.remote_field_name for field in mapped_fields]

        disallowed_fields = self.validate_permitted_fields(mapped_field_names, kwargs)

        if disallowed_fields:
            return {
                "status": "error",
                "message": f"Field(s) {', '.join(disallowed_fields)} on {model_name} are not allowed to be synchronized.",
            }

        non_duplicate_field_names = [
            (field.local_field_name, field.remote_field_name)
            for field in mapped_fields
            if not field.allow_duplicates
        ]

        duplicates_domain = []

        # Create a domain to check for potential duplicates
        for dupe_field in non_duplicate_field_names:
            field_name, remote_value_key = dupe_field
            field_value = kwargs.get(remote_value_key)

            if field_name in ["mobile", "phone", "mobile_connect"] and field_value:
                if format_msisdn(field_value, MSISDNFormat.E164.value):
                    formatted_number = format_msisdn(
                        field_value, MSISDNFormat.E164.value
                    )[1:]
                    field_value = formatted_number

            # Add the compound condition: field IS NOT FALSE AND field = value
            duplicates_domain += [
                "&",
                (field_name, "!=", False),
                (field_name, "=", field_value),
            ]

        # Combine all conditions with OR if there are multiple fields
        if len(non_duplicate_field_names) > 1:
            final_domain = ["|"] * (
                len(non_duplicate_field_names) - 1
            ) + duplicates_domain
        else:
            final_domain = duplicates_domain  # No need for OR if only one field

        _logger.info(f"Duplicates domain: {final_domain}")

        potential_duplicates = request.env[model_name].sudo().search(final_domain)

        _logger.info(f"Duplicate Records: {potential_duplicates}")

        if potential_duplicates and existing_record.id not in [
            x.id for x in potential_duplicates
        ]:
            remote_field_names_only = [x[1] for x in non_duplicate_field_names]
            return {
                "status": "error",
                "message": f"Duplicate values on {model_name} not allowed for field(s): {', '.join(remote_field_names_only)}.",
            }

        vals = {}

        for field in mapped_fields:
            if field.remote_field_name in kwargs:

                if (
                    field.remote_field_name in ["mobile", "phone", "mobile_connect"]
                    and kwargs[field.remote_field_name]
                ):
                    if format_msisdn(
                        kwargs[field.remote_field_name], MSISDNFormat.E164.value
                    ):
                        formatted_number = format_msisdn(
                            kwargs[field.remote_field_name], MSISDNFormat.E164.value
                        )[1:]
                        kwargs[field.remote_field_name] = formatted_number

                vals[field.local_field_name] = kwargs.get(field.remote_field_name)

        _logger.info(f"Values: {vals}")

        # Update record
        try:
            context = {"source_sync": True}
            vals["last_inbound_sync_date"] = datetime.now()
            result = existing_record.with_context(context).sudo().write(vals)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update {model_name}: {str(e)}",
            }

        return {
            "status": "success",
            "message": "Updated successfully",
            "id": existing_record.id,
            "result": result,
            "vals": vals,
        }
