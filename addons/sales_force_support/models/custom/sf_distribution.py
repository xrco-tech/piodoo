# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
import requests
import json
from datetime import datetime, timedelta
import random
import string

_logger = logging.getLogger(__name__)


class SFMappingField(models.Model):
    _name = "sf.mapping.field"
    _description = "Sales Force Field Mapping"

    local_model_id = fields.Many2one(comodel_name="ir.model", string="Local Model")
    local_model_name = fields.Char(related="local_model_id.model", string="Model Name")
    local_field_id = fields.Many2one(
        comodel_name="ir.model.fields", string="Local Field"
    )
    local_field_name = fields.Char(related="local_field_id.name", string="Field Name")
    remote_model_name = fields.Char(string="Remote Model Name")
    remote_model_description = fields.Char(string="Remote Model Description")
    remote_field_name = fields.Char(string="Remote Field Name")
    remote_field_description = fields.Char(string="Remote Field Description")
    inbound = fields.Boolean(string="Sync Inbound?")
    outbound = fields.Boolean(string="Sync Outbound?")
    required_on_create = fields.Boolean(string="Required on Create?")
    required_on_update = fields.Boolean(string="Required on Update?")
    edit_after_create = fields.Boolean(string="Edit after Create?")
    allow_duplicates = fields.Boolean(string="Allow Duplicates?", default=False)


class UserOTP(models.Model):
    _name = "user.otp"
    _description = "User One Time Pin"
    _order = "create_date desc"

    mobile = fields.Char(
        string="Mobile Number",
        required=True,
        help="Mobile number for OTP authentication",
    )

    pin = fields.Char(string="OTP Code", required=True, help="One Time Pin code")

    expiry_date = fields.Datetime(
        string="Expiry Date", required=True, help="OTP expiry date and time"
    )

    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("successful", "Successful"),
            ("failed", "Failed"),
            ("expired", "Expired"),
        ],
        string="Status",
        default="pending",
        required=True,
        help="Status of the OTP authentication attempt",
    )

    attempts = fields.Integer(
        string="Attempts", default=0, help="Number of authentication attempts"
    )

    max_attempts = fields.Integer(
        string="Max Attempts", default=3, help="Maximum allowed attempts"
    )

    is_used = fields.Boolean(
        string="Is Used",
        default=False,
        help="Whether the OTP has been successfully used",
    )

    sales_force_member_id = fields.Many2one(
        "sf.member",
        string="Related Sales Force Member",
        help="Sales force member related to this OTP",
    )

    @api.model
    def generate_otp(self, mobile, sales_force_member_id=None, validity_minutes=10):
        """
        Generate a new OTP for the given mobile number
        Args:
            mobile (str): Mobile number
            sales_force_member_id (int): Optional sales force member ID
            validity_minutes (int): OTP validity in minutes (default: 10)
        Returns:
            recordset: Created OTP record
        """
        otp_code = "".join(random.choices(string.digits, k=6))
        expiry_date = datetime.now() + timedelta(minutes=validity_minutes)

        existing_otps = self.search(
            [
                ("mobile", "=", mobile),
                ("status", "=", "pending"),
                ("expiry_date", ">", datetime.now()),
            ]
        )
        existing_otps.write({"status": "expired"})

        otp_record = self.create(
            {
                "mobile": mobile,
                "pin": otp_code,
                "expiry_date": expiry_date,
                "sales_force_member_id": sales_force_member_id,
                "status": "pending",
            }
        )

        return otp_record

    @api.model
    def verify_otp(self, mobile, entered_pin):
        """
        Verify OTP for the given mobile number
        Args:
            mobile (str): Mobile number
            entered_pin (str): OTP entered by user
        Returns:
            dict: Verification result with status and message
        """
        otp_record = self.search(
            [("mobile", "=", mobile), ("status", "=", "pending")], limit=1
        )

        if not otp_record:
            return {
                "success": False,
                "message": "No pending OTP found for this mobile number",
            }

        if otp_record.expiry_date < datetime.now():
            otp_record.status = "expired"
            return {"success": False, "message": "OTP has expired"}

        otp_record.attempts += 1

        if otp_record.attempts > otp_record.max_attempts:
            otp_record.status = "failed"
            return {"success": False, "message": "Maximum attempts exceeded"}

        if otp_record.pin == entered_pin:
            otp_record.write({"status": "successful", "is_used": True})

            if otp_record.sales_force_member_id:
                otp_record.sales_force_member_id.write(
                    {"last_app_login_date": datetime.now()}
                )

            return {
                "success": True,
                "message": "OTP verified successfully",
                "sales_force_member_id": (
                    otp_record.sales_force_member_id.id
                    if otp_record.sales_force_member_id
                    else None
                ),
            }
        else:
            if otp_record.attempts >= otp_record.max_attempts:
                otp_record.status = "failed"
                return {
                    "success": False,
                    "message": "Invalid OTP. Maximum attempts exceeded.",
                }
            else:
                return {
                    "success": False,
                    "message": f"Invalid OTP. {otp_record.max_attempts - otp_record.attempts} attempts remaining.",
                }

    @api.model
    def cleanup_expired_otps(self):
        """
        Cleanup expired OTPs (can be called via cron job)
        """
        expired_otps = self.search(
            [("expiry_date", "<", datetime.now()), ("status", "=", "pending")]
        )
        expired_otps.write({"status": "expired"})
        return len(expired_otps)

    def name_get(self):
        """
        Custom name for the record display
        """
        result = []
        for record in self:
            name = f"{record.mobile} - {record.pin} ({record.status})"
            result.append((record.id, name))
        return result
