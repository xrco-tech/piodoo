# -*- coding: utf-8 -*-
# Source: bb_payin
from odoo import models, api, fields, _
from odoo.tools.misc import format_date

from dateutil.relativedelta import relativedelta
from itertools import chain
import json

import logging

_logger = logging.getLogger(__name__)


class ReportPayInSheetsEnquiry(models.Model):
    _name = "bb.payin.sheets.enquiry.report"
    _description = "Pay-In Sheets Consultant Enquiry"
    _auto = False

    @api.model
    def _get_options(self, previous_options=None):
        # OVERRIDE
        options = super(ReportPayInSheetsEnquiry, self)._get_options(
            previous_options=previous_options
        )
        options["filter_account_type"] = "receivable"
        return options

    @api.model
    def _get_report_name(self):
        return _("Pay-In Sheets Consultant Enquiry")

    ####################################################
    # QUERIES
    ####################################################
    @api.model
    def get_payin_sheet_sql(self, partner):
        consultant_list = []
        partners = []
        _logger.info("partner: %s", partner)
        if isinstance(partner, dict):
            partners = ",".join(str(_) for _ in partner.get("partner_code"))
        else:
            partners = partner
        if not partners:
            pass
        else:
            query = """select bps.id as ID, bps."period" as Period, coalesce(bpsl.bb_sales, 0) as bb_sales, coalesce(bpsl.bb_returns, 0) as bb_returns,
                        coalesce(bpsl.bb_brand_total, 0) as bb_brand_total,
                        coalesce(bpsl.puer_sales, 0) as puer_sales, coalesce(bpsl.puer_returns, 0) as puer_returns, coalesce(bpsl.puer_brand_total, 0) as puer_brand_total,
                        coalesce(bpsl.bb_brand_total, 0) + coalesce(bpsl.puer_brand_total, 0) as TotalSales,
                        he.sales_force_code as ConsultantCode, he.name as ConsultantName,
                        he2.sales_force_code as ManagerCode, he2."name" as ManagerName,
                        he3.sales_force_code as DistributorCode, rp."name" as DistributorName,
                        bps.capture_start_date as CaptureDate
                        from bb_payin_sheet_line bpsl
                        left join bb_payin_sheet bps on bps.id = bpsl.payin_sheet_id
                        left join sf_member he on he.id = bpsl.consultant_id /* Consultant Level */
                        left join sf_member he2 on he2.id = bps.manager_id  /* Manager Level */
                        left join sf_member he3 on he3.id = bps.distributor_id  /* Distributor Level */
                        left join res_partner rp on rp.id = he3.partner_id /* Get distribution */
                        where he.id in ({}) and bps.state in ('verified')--or he.name ilike '%s' he.sales_force_code ilike '%s'
                        order by bps."date" desc
                """.format(
                partners
            )
            self.env.cr.execute(query)
            for rec in self.env.cr.dictfetchall():
                consultant_list.append(rec)
            _logger.info("consultant_list: %s", consultant_list)
        return consultant_list

    def get_report_filename(self, options):
        """The name that will be used for the file when downloading pdf,xlsx,..."""
        return self._get_report_name()

    def open_payin_sheet(self, options, params=None):
        module = "sales_force_support"
        view_name = "payin_form_view"
        # Decode params
        model = params.get("model", "account.move.line")
        res_id = params.get("id")

        view_id = self.env.ref(f"{module}.{view_name}").id
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [(view_id, "form")],
            "res_model": "bb.payin.sheet",
            "view_id": view_id,
            "res_id": res_id,
        }

    def print_pdf(self, options, params=None):
        _logger.info("This is  print Pdf")
        return {
            "type": "ir_actions_payin_sheet_report_download",
            "data": {
                "model": self.env.context.get("model"),
                "options": json.dumps(options),
                "output_format": "pdf",
                "enquiry_id": options.get("partner_ids"),
                "allowed_company_ids": self.env.context.get("allowed_company_ids"),
            },
        }
