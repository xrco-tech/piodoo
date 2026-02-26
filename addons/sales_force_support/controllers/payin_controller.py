# -*- coding: utf-8 -*-
# Source: bb_payin/controllers/main.py
from odoo import http
from odoo.http import content_disposition, request

# from odoo.addons.web.controllers.main import _serialize_exception
from odoo.tools import html_escape

import json
import logging

_logger = logging.getLogger(__name__)


class PayInSheetEnquiryReportController(http.Controller):
    @http.route(
        "/payin_sheet_reports", type="http", auth="user", methods=["POST"], csrf=False
    )
    def get_report(self, model, options, output_format, token, enquiry_id=None, **kw):
        uid = request.session.uid
        account_report_model = request.env["bb.payin.sheets.enquiry.report"]
        options = json.loads(options)
        cids = kw.get("allowed_company_ids")
        if not cids or cids == "null":
            cids = request.httprequest.cookies.get(
                "cids", str(request.env.user.company_id.id)
            )
        allowed_company_ids = [int(cid) for cid in cids.split(",")]
        report_obj = (
            request.env["bb.payin.sheets.enquiry.report"]
            .with_user(uid)
            .with_context(allowed_company_ids=allowed_company_ids)
        )
        report_name = report_obj.get_report_filename(options)
        if enquiry_id and enquiry_id != "null":
            report_data = report_obj.get_payin_sheet_sql(enquiry_id)

        print(f"Report Obj: {report_obj} - Report Name: {report_name}")
        try:
            if output_format == "pdf":
                response = request.make_response(
                    report_obj.get_pdf(options),
                    headers=[
                        (
                            "Content-Type",
                            account_report_model.get_export_mime_type("pdf"),
                        ),
                        (
                            "Content-Disposition",
                            content_disposition(report_name + ".pdf"),
                        ),
                    ],
                )
        except Exception as e:
            # se = _serialize_exception(e)
            error = {
                "code": 200,
                "message": "Odoo Server Error",
                # 'data': se
            }


class XLSXReportController(http.Controller):

    @http.route("/xlsx_reports", type="http", auth="user", methods=["POST"], csrf=False)
    def get_report_xlsx(self, model, options, output_format, token, report_name, **kw):
        _logger.info("model %s", model)
        _logger.info("options %s", options)
        _logger.info("output_format %s", output_format)
        _logger.info("token %s", token)
        _logger.info("report_name %s", report_name)
        _logger.info("kw %s", kw)
        uid = request.session.uid
        report_obj = request.env[model].with_user(uid)
        options = json.loads(options)
        _logger.info(options)
        try:
            if output_format == "xlsx":
                full_report_name = self.get_report_data(options, report_name)
                response = request.make_response(
                    None,
                    headers=[
                        ("Content-Type", "application/vnd.ms-excel"),
                        (
                            "Content-Disposition",
                            content_disposition(full_report_name + ".xlsx"),
                        ),
                    ],
                )
                report_obj.get_xlsx_report(options, response)

            response.set_cookie("fileToken", token)
            return response
        except Exception as e:
            # se = _serialize_exception(e)
            error = {
                "code": 200,
                "message": "Odoo Server Error",
                # 'data': se
            }
            return request.make_response(html_escape(json.dumps(error)))

    def get_report_data(self, options, report_name):
        record_id = options.get("records")  # get the record id with a default of none.

        if record_id:
            record_data = (
                request.env["bb.payin.sheet"].sudo().search([("id", "=", record_id)])
            )

            if record_data:
                for record in record_data:
                    record_name = record.name  # Get the record name
                    distributor_known_name = record.distributor_known_name
                    parts = record_name.split(" / ")  # Split the name by " / "

                    if len(parts) == 3:  # Check if the name has the expected format
                        month_year, name, identifier = parts
                        name = name
                        month_year = month_year
                        combined_name = (
                            f"{distributor_known_name} {month_year} {report_name}"
                        )
                    else:
                        combined_name = record_name
                return combined_name
            else:
                _logger.warning("No record found with ID: %s", record_id)
                return False
        else:
            _logger.warning("No 'records' key found in options.")
            return False  # or raise an exception.
