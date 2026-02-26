# -*- coding: utf-8 -*-
# Source: bb_payin/models/voip_inheritence.py
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
from datetime import datetime, timedelta
from odoo.tools.safe_eval import dateutil


_logger = logging.getLogger(__name__)


class VoipCall(models.Model):
    _inherit = "voip.call"
    _description = "VoIP Phone call"

    res_id = fields.Integer("res_id")
    number = fields.Char("number")
    model = fields.Char("model")
    duration_seconds = fields.Integer("duration_seconds")
    message_ids = fields.Many2many(
        "mail.message", "voip_call_mail_message_rel", "call_id", "message_id"
    )
    received_voice_file = fields.Boolean("Received Voice File")
    requests_attempt_count = fields.Integer("No of Requests Attempted")
    voice_file_id = fields.Many2one("ir.attachment", string="Voice File")
    server = fields.Char("Telviva File Server")
    uniqueid = fields.Char("Telviva File Unique ID")
    record_id = fields.Char("Telviva File ID")

    def abort_call(self):
        res = super().abort_call()
        if self.model:
            self.write_to_chatter_for_widget()
        else:
            self.write_to_chatter_for_number(self.phone_number)
        return res

    def end_call(self, activity_name: str = None) -> list:
        result = super().end_call(activity_name)
        duration = self.end_date - self.start_date
        duration_seconds = int(duration.total_seconds())

        self.write({"duration_seconds": duration_seconds})

        # write to chatter
        if self.model:
            if duration_seconds > 0:
                self.write_to_chatter_for_widget()
        else:
            self.write_to_chatter_for_number(self.phone_number)
        return result

    def write_to_chatter_for_widget(self):
        # search for partner using phone number
        partner_id = self.env["res.partner"].search(
            [("mobile", "=", self.phone_number)], limit=1
        )

        if partner_id.view_model == "res.partner":
            rec_id = partner_id
        else:
            rec_id = self.env[partner_id.view_model].search(
                [("partner_id", "=", partner_id.id)], limit=1
            )
        rec_name = self.env[self.model].search([("id", "=", self.res_id)], limit=1)

        rec_type = ""
        if rec_name.id:
            if self.model == "bb.payin.sheet":
                rec_type = rec_type + "Pay-In Sheet"
            elif self.model == "payin.distributor":
                rec_type = rec_type + "Pay-In Sheet Distributor Summary"
        else:
            raise ValidationError("Record Not Found")

        if self.state in ["aborted", "rejected"]:
            message = (
                f"{self.env.user.name} attempted to call {rec_id.name} "
                f"on {self._change_date_fromat(self.create_date)}."
            )
        else:
            message = (
                f"{rec_id.name} was called by {self.env.user.name}  "
                f"on {self._change_date_fromat(self.start_date)} "
                f"for {self.formating_time(self.duration_seconds)} minutes."
            )

        # write to the chatter of the current screen
        self.env["mail.message"].create(
            {
                "author_id": self.env.user.partner_id.id,
                "model": self.model,
                "body": message,
                "res_id": self.res_id,
            }
        )

        # write to the chatter of the second screen
        if self.model != partner_id.view_model:
            self.env["mail.message"].create(
                {
                    "author_id": self.env.user.partner_id.id,
                    "model": partner_id.view_model,
                    "body": message,
                    "res_id": rec_id.id,
                }
            )

        self._write_to_chatter_event_registration()
        return

    @api.model
    def write_to_chatter_for_number(self, phone):
        partner_id = self.env["res.partner"].search([("mobile", "=", phone)], limit=1)

        if partner_id:
            if partner_id.view_model == "res.partner":
                rec = partner_id
            else:
                rec = self.env[partner_id.view_model].search(
                    [("partner_id", "=", partner_id.id)], limit=1
                )
            if self.state in ["aborted", "rejected"]:
                message = (
                    f"{self.env.user.name} attempted to call {rec.name} "
                    f"on {self._change_date_fromat(self.create_date)}."
                )
            else:
                message = (
                    f"{rec.name} was called by {self.env.user.name} from the Dialer on "
                    f"{self._change_date_fromat(self.start_date)} "
                    f"for {self.formating_time(self.duration_seconds)} minutes."
                )

            self.env["mail.message"].create(
                {
                    "author_id": self.env.user.partner_id.id,
                    "model": partner_id.view_model,
                    "body": message,
                    "res_id": rec.id,
                }
            )

        self._write_to_chatter_event_registration()
        return

    def _change_date_fromat(self, input_datetime):
        sast_datetime = input_datetime + dateutil.relativedelta.relativedelta(hours=2)
        formatted_date = sast_datetime.strftime("%d %m %Y %H:%M:%S")
        parsed_datetime = datetime.strptime(formatted_date, "%d %m %Y %H:%M:%S")
        output_datetime = parsed_datetime.strftime("%e %B %Y %H:%M:%S")
        return output_datetime

    def formating_time(self, seconds):
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        duration = f"{'{:02d}'.format(minutes)}:{'{:02d}'.format(remaining_seconds)}"
        return duration

    def _write_to_chatter_event_registration(self):
        formatted_phone_number = "+" + self.phone_number
        registration_id = self.env["event.registration"].search(
            [
                "|",
                ("phone", "=", formatted_phone_number),
                ("phone", "=", self.phone_number),
            ],
            order="create_date desc",
        )
        if registration_id:
            registration = registration_id[0]

            if self.state in ["aborted", "rejected"]:
                message = (
                    f"{self.env.user.name} attempted to call {registration.name} "
                    f"on {self._change_date_fromat(self.create_date)}."
                )
            else:
                message = (
                    f"{registration.name} was called by {self.env.user.name} from the Dialer on "
                    f"{self._change_date_fromat(self.start_date)} "
                    f"for {self.formating_time(self.duration_seconds)} minutes."
                )
            self.env["mail.message"].create(
                {
                    "author_id": self.env.user.partner_id.id,
                    "model": "event.registration",
                    "body": message,
                    "res_id": registration.id,
                }
            )
        return
