# Source: bb_payin/reports/captured_payin_sheet_report.py
from odoo import api, models, _
from odoo.exceptions import UserError


class PayInCapturedReport(models.AbstractModel):
    _name = "report.sales_force_support.report_captured_payin_sheets"
    _description = "Capture PayIn Sheets Report"

    def _get_report_values(self, docids, data):
        report_print_count = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sales_force_support.report_print_count")
        )

        # Check in the tracker table if this report was printed or not
        report_rec = self.env["captured.payinsheet.report.track"].search(
            [("payin_ids", "in", docids)], order="id desc", limit=1
        )

        if not report_rec:
            # Create the record in the table with relevant information
            vals = {"payin_ids": docids[0], "print_state": "printed", "print_count": 1}

            self.env["captured.payinsheet.report.track"].create(vals)

        # Raise Exception if User tries to reprint the report without relevant access rights
        if report_rec.print_count >= int(
            report_print_count
        ):
            raise UserError(
                _(
                    "You are not allowed to reprint the %s - %s - Captured Pay-In Sheets Report"
                    % (
                        report_rec.payin_ids.manager_id.name,
                        report_rec.payin_ids.manager_id.sales_force_code,
                    )
                )
            )

        if report_rec:
            # Update the record in the table with relevant information
            vals = {
                "print_state": "reprinted",
                "print_count": report_rec.print_count + 1,
            }

            report_rec.write(vals)
            self._track_report_print(
                report_track_rec=report_rec,
                payin_rec=self.env["bb.payin.sheet"].search(
                    [("id", "=", report_rec.payin_ids.id)], order="id desc", limit=1
                ),
            )

        docs = self.env["bb.payin.sheet"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "bb.payin.sheet",
            "data": data,
            "docs": docs,
            "proforma": True,
        }

    def _track_report_print(self, report_track_rec, payin_rec):
        message = f"{payin_rec.manager_id.name} - {payin_rec.manager_id.sales_force_code} - Captured Pay-In Sheets Report reprint for {report_track_rec.print_count} times."
        payin_rec.env["mail.message"].create(
            {
                "author_id": report_track_rec.write_uid.partner_id.id,
                "model": "bb.payin.sheet",
                "body": message,
                "res_id": payin_rec.id,
            }
        )


class DistributorSummaryCapturedReport(models.AbstractModel):
    _name = "report.sales_force_support.report_new_distributor_captured"
    _description = "Capture Distributor Summary Report"

    def _get_report_values(self, docids, data):
        report_print_count = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sales_force_support.report_print_count")
        )

        # Check in the tracker table if this report was printed or not
        report_rec = self.env["captured.summary.report.track"].search(
            [("payin_ids", "in", docids)], order="id desc", limit=1
        )

        if not report_rec:
            # Create the record in the table with relevant information
            vals = {"payin_ids": docids[0], "print_state": "printed", "print_count": 1}

            self.env["captured.summary.report.track"].create(vals)

        # Raise Exception if User tries to reprint the report without relevant access rights
        if report_rec.print_count >= int(
            report_print_count
        ):
            raise UserError(
                _(
                    "You are not allowed to reprint the %s - %s - Captured Distributor Summary Report"
                    % (
                        report_rec.payin_ids.distributor_id.name,
                        report_rec.payin_ids.distributor_id.sales_force_code,
                    )
                )
            )

        if report_rec:
            # Update the record in the table with relevant information
            vals = {
                "print_state": "reprinted",
                "print_count": report_rec.print_count + 1,
            }

            report_rec.write(vals)
            self._track_report_print(
                report_track_rec=report_rec,
                payin_rec=self.env["payin.distributor"].search(
                    [("id", "=", report_rec.payin_ids.id)], order="id desc", limit=1
                ),
            )

        docs = self.env["payin.distributor"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "payin.distributor",
            "data": data,
            "docs": docs,
            "proforma": True,
        }

    def _track_report_print(self, report_track_rec, payin_rec):
        message = f"{payin_rec.distributor_id.name} - {payin_rec.distributor_id.sales_force_code} - Captured Distributor Summary Report reprint for {report_track_rec.print_count} times."
        payin_rec.env["mail.message"].create(
            {
                "author_id": report_track_rec.write_uid.partner_id.id,
                "model": "payin.distributor",
                "body": message,
                "res_id": payin_rec.id,
            }
        )
