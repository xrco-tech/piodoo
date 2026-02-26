# Source: bb_payin/wizards/capture.py
# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
import math


_logger = logging.getLogger(__name__)


class CaptureWizard(models.TransientModel):
    _name = "capture.wizard"

    sheet_id = fields.Many2one("bb.payin.sheet", "Pay-In Sheet")
    sheet_id_dist = fields.Many2one("payin.distributor", "Distributor Pay-In Sheet")
    payin_message = fields.Char(
        "Pay-In Message",
        default="Please confirm that you have completed your Pay-In Sheet capture.",
    )
    summary_message = fields.Char(
        "Distributor Summary Message",
        default="Please confirm that you have completed your Pay-In Sheet Distributor Summary capture.",
    )
    do_nothing = fields.Boolean("Do Nothing")

    def captured(self):
        if self.do_nothing:
            self.sheet_id.is_no_sales = True
        else:
            payin_date = self.sheet_id.payin_date

            sold_payin_lines = [
                line
                for line in self.sheet_id.payin_line_ids
                if line.bb_brand_total > 0 or line.puer_brand_total > 0
            ]

            for line in sold_payin_lines:
                _logger.info("line: %s", line)
                _logger.info("consultant_id: %s", line.consultant_id)
                employee_id = line.consultant_id.id
                current_job_id = line.consultant_id.genealogy
                manager_id = line.consultant_id.manager_id.id
                manager_code = line.consultant_id.manager_id.sales_force_code
                distributor_code = (
                    line.consultant_id.related_distributor_id.sales_force_code
                )

                personal_bbb_sale = line.bb_brand_total
                personal_puer_sale = line.puer_brand_total

                active_status = line.consultant_id.active_status

                create_history_vals = {
                    "payin_date": payin_date,
                    "employee_id": employee_id,
                    "current_job_id": current_job_id,
                    "manager_id": manager_id,
                    "manager_code": manager_code,
                    "distributor_code": distributor_code,
                    "personal_bbb_sale": personal_bbb_sale,
                    "personal_puer_sale": personal_puer_sale,
                    "active_status": active_status,
                }

                self.env["bb.payin.history"].create(create_history_vals)

                line.consultant_id.update_consultant_sales_activity_info(payin_date)

        self.sheet_id.state = "captured"
        self.sheet_id.user_id = self.env.user.id
        self.sheet_id.action_timer_stop()

        return True

    def do_nothing_function(self):
        for line in self.sheet_id.payin_line_ids:
            history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "=", line.payin_sheet_id.payin_date),
                    ("employee_id", "=", line.consultant_id.id),
                ]
            )
            if not history_id:
                team_promoted = 0
                if line.consultant_id.genealogy in [
                    "manager",
                    "prospective_distributor",
                ]:
                    previous_history_id = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.id),
                        ],
                        order="payin_date desc",
                        limit=1,
                    )
                    if previous_history_id:
                        team_promoted = previous_history_id.team_promoted

                history_id = self.env["bb.payin.history"].create(
                    {
                        "payin_date": line.payin_sheet_id.payin_date,
                        "employee_id": line.consultant_id.id,
                        "team_promoted": team_promoted,
                        "active_status": line.consultant_id.active_status,
                        "current_job_id": line.consultant_id.genealogy,
                        "manager_code": line.consultant_id.manager_id.sales_force_code,
                        "distributor_code": line.consultant_id.related_distributor_id.sales_force_code,
                        "manager_id": line.consultant_id.manager_id.id,
                    }
                )

            # Personal Sales
            history_id.active_status = line.consultant_id.active_status
            history_id.personal_bbb_sale = line.bb_brand_total
            history_id.personal_puer_sale = line.puer_brand_total
            previous_history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "<", line.payin_sheet_id.payin_date),
                    ("employee_id", "=", line.consultant_id.id),
                ],
                order="payin_date desc",
                limit=1,
            )
            if previous_history_id:
                history_id.team_promoted = previous_history_id.team_promoted

            # Team Sales manager
            if line.consultant_id.id != line.payin_sheet_id.manager_id.id:
                history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "=", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.manager_id.id),
                    ]
                )
                if not history_id:
                    team_promoted = 0
                    if line.consultant_id.manager_id.genealogy in [
                        "manager",
                        "prospective_distributor",
                    ]:
                        previous_history_id = self.env["bb.payin.history"].search(
                            [
                                ("payin_date", "<", line.payin_sheet_id.payin_date),
                                ("employee_id", "=", line.consultant_id.manager_id.id),
                            ],
                            order="payin_date desc",
                            limit=1,
                        )
                        if previous_history_id:
                            team_promoted = previous_history_id.team_promoted
                    history_id = self.env["bb.payin.history"].create(
                        {
                            "payin_date": line.payin_sheet_id.payin_date,
                            "employee_id": line.consultant_id.manager_id.id,
                            "active_status": line.consultant_id.manager_id.active_status,
                            "team_promoted": team_promoted,
                            "current_job_id": line.consultant_id.manager_id.genealogy,
                            "manager_code": line.consultant_id.manager_id.manager_id.sales_force_code,
                            "distributor_code": line.consultant_id.manager_id.related_distributor_id.sales_force_code,
                            "manager_id": line.consultant_id.manager_id.manager_id.id,
                        }
                    )
                history_id.active_status = line.consultant_id.manager_id.active_status
                history_id.team_bbb_sales += line.bb_brand_total
                history_id.team_puer_sales += line.puer_brand_total
                if line.consultant_id.manager_id.genealogy in [
                    "manager",
                    "prospective_distributor",
                ]:
                    previous_history_id = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.manager_id.id),
                        ],
                        order="payin_date desc",
                        limit=1,
                    )
                    if previous_history_id:
                        history_id.team_promoted = previous_history_id.team_promoted

            # Team Sales recuited by

            if line.consultant_id.recruiter_id.genealogy in [
                "consultant",
                "prospective_manager",
            ]:
                history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "=", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.recruiter_id.id),
                    ]
                )
                if not history_id:
                    team_promoted = 0
                    if line.consultant_id.recruiter_id.genealogy in [
                        "manager",
                        "prospective_distributor",
                    ]:
                        previous_history_id = self.env["bb.payin.history"].search(
                            [
                                ("payin_date", "<", line.payin_sheet_id.payin_date),
                                (
                                    "employee_id",
                                    "=",
                                    line.consultant_id.recruiter_id.id,
                                ),
                            ],
                            order="payin_date desc",
                            limit=1,
                        )
                        if previous_history_id:
                            team_promoted = previous_history_id.team_promoted
                    history_id = self.env["bb.payin.history"].create(
                        {
                            "payin_date": line.payin_sheet_id.payin_date,
                            "employee_id": line.consultant_id.recruiter_id.id,
                            "active_status": line.consultant_id.recruiter_id.active_status,
                            "current_job_id": line.consultant_id.recruiter_id.genealogy,
                            "team_promoted": team_promoted,
                            "manager_code": line.consultant_id.recruiter_id.manager_id.sales_force_code,
                            "distributor_code": line.consultant_id.recruiter_id.related_distributor_id.sales_force_code,
                            "manager_id": line.consultant_id.recruiter_id.manager_id.id,
                        }
                    )
                history_id.active_status = line.consultant_id.active_status
                history_id.team_bbb_sales += line.bb_brand_total
                history_id.team_puer_sales += line.puer_brand_total
                if line.consultant_id.recruiter_id.genealogy in [
                    "manager",
                    "prospective_distributor",
                ]:
                    previous_history_id = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.recruiter_id.id),
                        ],
                        order="payin_date desc",
                        limit=1,
                    )
                    if previous_history_id:
                        history_id.team_promoted = previous_history_id.team_promoted

            if (
                line.consultant_id.manager_id
                and line.consultant_id.manager_id.id
                != line.consultant_id.recruiter_id.id
            ):
                history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "=", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.manager_id.id),
                    ]
                )
                if not history_id:
                    team_promoted = 0
                    if line.consultant_id.manager_id.genealogy in [
                        "manager",
                        "prospective_distributor",
                    ]:
                        previous_history_id = self.env["bb.payin.history"].search(
                            [
                                ("payin_date", "<", line.payin_sheet_id.payin_date),
                                ("employee_id", "=", line.consultant_id.manager_id.id),
                            ],
                            order="payin_date desc",
                            limit=1,
                        )
                        if previous_history_id:
                            team_promoted = previous_history_id.team_promoted
                    history_id = self.env["bb.payin.history"].create(
                        {
                            "payin_date": line.payin_sheet_id.payin_date,
                            "employee_id": line.consultant_id.manager_id.id,
                            "active_status": line.consultant_id.manager_id.active_status,
                            "current_job_id": line.consultant_id.manager_id.genealogy,
                            "team_promoted": team_promoted,
                            "manager_code": line.consultant_id.manager_id.manager_id.sales_force_code,
                            "distributor_code": line.consultant_id.manager_id.related_distributor_id.sales_force_code,
                            "manager_id": line.consultant_id.manager_id.manager_id.id,
                        }
                    )
                history_id.active_status = line.consultant_id.active_status
                history_id.team_bbb_sales += line.bb_brand_total
                history_id.team_puer_sales += line.puer_brand_total
                if line.consultant_id.manager_id.genealogy in [
                    "manager",
                    "prospective_distributor",
                ]:
                    previous_history_id = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.manager_id.id),
                        ],
                        order="payin_date desc",
                        limit=1,
                    )
                    if previous_history_id:
                        history_id.team_promoted = previous_history_id.team_promoted

        self.sheet_id.action_timer_stop()

    def update_manager_promotion_fields(self, count):
        manager_history_id = self.env["bb.payin.history"].search(
            [
                ("payin_date", "=", self.sheet_id.payin_date),
                ("employee_id", "=", self.sheet_id.manager_id.id),
            ]
        )
        if self.sheet_id.manager_id.promoter_id:
            manager_history_id.promoted_by = self.sheet_id.manager_id.promoter_id.id

        promotion_rule_id = self.env["promotion.rules"].search(
            [("current_genealogy_level", "=", self.sheet_id.manager_id.genealogy)],
            limit=1,
        )
        if promotion_rule_id:
            date = self.sheet_id.payin_date.replace(month=1)
            dates_to_exclude = []
            for month in promotion_rule_id.months_to_exclude_ids:
                if date > self.sheet_id.payin_date:
                    date = date.replace(year=date.year - 1)
                dates_to_exclude.append(date)

            if (
                manager_history_id.total_team_sales
                >= promotion_rule_id.team_sales_value
            ):
                history_ids = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<=", self.sheet_id.payin_date),
                        ("employee_id", "=", self.sheet_id.manager_id.id),
                        ("payin_date", "not in", dates_to_exclude),
                    ],
                    limit=promotion_rule_id.manager_sales_month,
                    order="payin_date desc",
                )
                team_sales_promotion = True
                if len(history_ids.ids) < promotion_rule_id.manager_sales_month:
                    team_sales_promotion = False
                else:
                    for history in history_ids:
                        if (
                            history.total_team_sales
                            < promotion_rule_id.team_sales_value
                        ):
                            team_sales_promotion = False
                manager_history_id.team_sales_promotion = team_sales_promotion
            else:
                manager_history_id.team_sales_promotion = False

        promoded_by_id = self.sheet_id.manager_id.promoter_id
        if promoded_by_id:
            promoted_by_history_id = self.env["bb.payin.history"].search(
                [
                    ("employee_id", "=", promoded_by_id.id),
                    ("payin_date", "=", self.sheet_id.payin_date),
                ],
                limit=1,
            )
            if not promoted_by_history_id:
                team_promoted = 0
                previous_history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<", self.sheet_id.payin_date),
                        ("employee_id", "=", promoded_by_id.id),
                    ],
                    order="payin_date desc",
                    limit=1,
                )
                if previous_history_id:
                    team_promoted = previous_history_id.team_promoted
                promoted_by_history_id = self.env["bb.payin.history"].create(
                    {
                        "payin_date": self.sheet_id.payin_date,
                        "employee_id": promoded_by_id.id,
                        "team_promoted": team_promoted,
                        "active_status": promoded_by_id.active_status,
                        "current_job_id": promoded_by_id.genealogy,
                        "manager_code": promoded_by_id.manager_id.sales_force_code,
                        "distributor_code": promoded_by_id.related_distributor_id.sales_force_code,
                        "manager_id": promoded_by_id.manager_id.id,
                    }
                )
            previous_history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "<", self.sheet_id.payin_date),
                    ("employee_id", "=", promoded_by_id.id),
                ],
                order="payin_date desc",
                limit=1,
            )
            if previous_history_id:
                previous_history_id.team_promoted = previous_history_id.team_promoted
            promoded_by_promotion_rule_id = self.env["promotion.rules"].search(
                [("current_genealogy_level", "=", promoded_by_id.genealogy)], limit=1
            )
            # promoted_by_history_id.pbm_promoted_avtive_consultants += 1
            if (
                manager_history_id.active_sfm_this_month
                >= promoded_by_promotion_rule_id.promoted_manager_active_consultants
            ):
                manager_history_id.manager_promote_avtive_consultants = True

                date = self.sheet_id.payin_date.replace(month=1)
                dates_to_exclude = []
                for month in promotion_rule_id.months_to_exclude_ids:
                    if date > self.sheet_id.payin_date:
                        date = date.replace(year=date.year - 1)
                    dates_to_exclude.append(date)
                history_ids = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<=", self.sheet_id.payin_date),
                        ("employee_id", "=", self.sheet_id.manager_id.id),
                        ("payin_date", "not in", dates_to_exclude),
                    ],
                    limit=promoded_by_promotion_rule_id.promoted_managers_moths,
                    order="payin_date desc",
                )
                manager_promote_avtive_consultants = True
                if (
                    len(history_ids)
                    < promoded_by_promotion_rule_id.promoted_managers_moths
                ):
                    manager_promote_avtive_consultants = False
                else:
                    for history in history_ids:
                        if (
                            history.team_bbb_sales + history.team_puer_sales
                            < promotion_rule_id.team_sales_value
                        ):
                            manager_promote_avtive_consultants = False
                manager_history_id.manager_promote_avtive_consultants = (
                    manager_promote_avtive_consultants
                )

            if manager_history_id.manager_promote_avtive_consultants:
                promoted_by_history_id.pbm_promoted_avtive_consultants += 1

                if (
                    promoted_by_history_id.pbm_promoted_avtive_consultants
                    >= promoded_by_promotion_rule_id.promoted_managers
                ):
                    promoted_by_history_id.pbm_promoted_managers_active_promotion = True

            if (
                manager_history_id.total_team_sales
                >= promoded_by_promotion_rule_id.team_sales_value_per_promoted_manager
            ):
                date = self.sheet_id.payin_date.replace(month=1)
                dates_to_exclude = []
                for month in promotion_rule_id.months_to_exclude_ids:
                    if date > self.sheet_id.payin_date:
                        date = date.replace(year=date.year - 1)
                    dates_to_exclude.append(date)
                history_ids = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<=", self.sheet_id.payin_date),
                        ("employee_id", "=", self.sheet_id.manager_id.id),
                        ("payin_date", "not in", dates_to_exclude),
                    ],
                    limit=promoded_by_promotion_rule_id.promoted_team_sales_month,
                    order="payin_date desc",
                )
                manager_history_id.manger_promoted_sales_above = True
                if (
                    len(history_ids)
                    < promoded_by_promotion_rule_id.promoted_team_sales_month
                ):
                    manager_history_id.manger_promoted_sales_above = False
                else:
                    for history in history_ids:
                        if (
                            history.total_team_sales
                            < promoded_by_promotion_rule_id.team_sales_value_per_promoted_manager
                        ):
                            manager_history_id.manger_promoted_sales_above = False

            else:
                manager_history_id.manger_promoted_sales_above = False

            if manager_history_id.manger_promoted_sales_above:
                promoted_by_history_id.pbm_promoted_managers_team_sales_above += 1

                if (
                    promoted_by_history_id.pbm_promoted_managers_team_sales_above
                    >= promoded_by_promotion_rule_id.promoted_managers
                ):
                    promoted_by_history_id.pbm_team_sales_above = True
                else:
                    promoted_by_history_id.pbm_team_sales_above = False

        history_id = self.env["bb.payin.history"].search(
            [
                ("payin_date", "=", self.sheet_id.payin_date),
                ("employee_id", "=", self.sheet_id.distributor_id.id),
            ],
            limit=1,
        )
        if not history_id:
            history_id = self.env["bb.payin.history"].create(
                {
                    "payin_date": self.sheet_id.payin_date,
                    "employee_id": self.sheet_id.distributor_id.id,
                    "active_status": self.sheet_id.distributor_id.active_status,
                    "current_job_id": self.sheet_id.distributor_id.genealogy,
                    "manager_code": self.sheet_id.distributor_id.manager_id.sales_force_code,
                    "distributor_code": self.sheet_id.distributor_id.related_distributor_id.sales_force_code,
                    "manager_id": self.sheet_id.distributor_id.manager_id.id,
                }
            )
        manager_history_id = self.env["bb.payin.history"].search(
            [
                ("payin_date", "=", self.sheet_id.payin_date),
                ("employee_id", "=", self.sheet_id.manager_id.id),
            ],
            limit=1,
        )
        history_id.team_bbb_sales += manager_history_id.team_bbb_sales
        history_id.team_puer_sales += manager_history_id.team_puer_sales

    def update_lead_fields(self, line):
        if line.consultant_id.id and not line.consultant_id.first_sale_date:
            # todo: only update first sales date for consultants with sales, also move this to the relevant function
            line.consultant_id.first_sale_date = fields.Date.today()
            if line.consultant_id.genealogy == "potential_consultant":
                line.consultant_id.genealogy = "consultant"
        if line.consultant_id.id and not line.consultant_id.sale:
            line.consultant_id.sale = True
            for applicant in self.env["sf.recruit"].search(
                [("emp_id", "=", line.consultant_id.id)]
            ):
                applicant.stage_id = (
                    self.env["sf.recruit.stage"]
                    .search(
                        [("name", "=", "Consultant"), ("sales_force", "=", True)],
                        limit=1,
                    )
                    .id
                )

    def update_recruited_by_record(self, line, dates_to_exclude):
        if line.consultant_id.recruiter_id.genealogy in [
            "consultant",
            "prospective_manager",
        ]:
            history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "=", line.payin_sheet_id.payin_date),
                    ("employee_id", "=", line.consultant_id.recruiter_id.id),
                ]
            )
            if not history_id:
                history_id = self.env["bb.payin.history"].create(
                    {
                        "payin_date": line.payin_sheet_id.payin_date,
                        "employee_id": line.consultant_id.recruiter_id.id,
                        "active_status": line.consultant_id.recruiter_id.active_status,
                        "current_job_id": line.consultant_id.recruiter_id.genealogy,
                        "manager_code": line.consultant_id.recruiter_id.manager_id.sales_force_code,
                        "distributor_code": line.consultant_id.recruiter_id.related_distributor_id.sales_force_code,
                        "manager_id": line.consultant_id.recruiter_id.manager_id.id,
                    }
                )
            history_id.active_status = line.consultant_id.active_status
            history_id.team_bbb_sales += line.bb_brand_total
            history_id.team_puer_sales += line.puer_brand_total
            if line.sub_total != 0:
                history_id.active_sfm_this_month += 1

            # consultant or prospective manager promotions
            promotion_rule_id = self.env["promotion.rules"].search(
                [
                    (
                        "current_genealogy_level",
                        "=",
                        line.consultant_id.recruiter_id.genealogy,
                    )
                ],
                limit=1,
            )
            if promotion_rule_id:
                history_ids = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<=", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.recruiter_id.id),
                        ("payin_date", "not in", dates_to_exclude),
                    ],
                    limit=promotion_rule_id.sales_month,
                    order="payin_date desc",
                )

                active_80 = True
                personal_80 = True
                team_80 = True
                if len(history_ids.ids) < promotion_rule_id.sales_month:
                    active_80 = False
                    personal_80 = False
                    team_80 = False
                else:
                    for history in history_ids:
                        # Calculating 80%
                        if (
                            history.active_sfm_this_month
                            * 100
                            / promotion_rule_id.retained_consultants
                            < 80
                        ):
                            active_80 = False

                        if (
                            history.personal_bbb_sale + history.personal_puer_sale
                        ) * 100 / promotion_rule_id.own_sales_value < 80:
                            personal_80 = False

                        if (
                            history.team_bbb_sales + history.team_puer_sales
                        ) * 100 / promotion_rule_id.team_sales_value < 80:
                            team_80 = False
                history_id.active_80 = active_80
                history_id.team_80 = team_80
                history_id.personal_80 = personal_80

                if (
                    history_id.active_sfm_this_month
                    >= promotion_rule_id.retained_consultants
                ):
                    date = line.payin_sheet_id.payin_date.replace(month=1)
                    dates_to_exclude = []
                    for month in promotion_rule_id.months_to_exclude_ids:
                        if date > line.payin_sheet_id.payin_date:
                            date = date.replace(year=date.year - 1)
                        dates_to_exclude.append(date)

                    # Updating personal Sales & team sales

                    # date_sale = date_sale - relativedelta(months=+self.date_sale)
                    history_ids = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<=", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.recruiter_id.id),
                            ("payin_date", "not in", dates_to_exclude),
                        ],
                        limit=promotion_rule_id.sales_month,
                        order="payin_date desc",
                    )
                    active_sfm_promotion = True
                    personal_sales_promotion = True
                    team_sales_promotion = True
                    if len(history_ids.ids) < promotion_rule_id.sales_month:
                        personal_sales_promotion = False
                        team_sales_promotion = False

                    else:
                        for history in history_ids:

                            # Updating personal

                            if (
                                history.personal_bbb_sale + history.personal_puer_sale
                                < promotion_rule_id.own_sales_value
                            ):
                                personal_sales_promotion = False

                            # Update team sales

                            if (
                                history.personal_bbb_sale + history.personal_puer_sale
                                < promotion_rule_id.own_sales_value
                            ):
                                if (
                                    history.team_bbb_sales + history.team_puer_sales
                                    < promotion_rule_id.team_sales_value
                                ):
                                    team_sales_promotion = False

                        history_id.team_sales_promotion = team_sales_promotion
                        # history_id.personal_sales_promotion = personal_sales_promotion
                    history_ids = self.env["bb.payin.history"].search(
                        [
                            ("payin_date", "<=", line.payin_sheet_id.payin_date),
                            ("employee_id", "=", line.consultant_id.recruiter_id.id),
                            ("payin_date", "not in", dates_to_exclude),
                        ],
                        limit=promotion_rule_id.months_retained_consultants,
                        order="payin_date desc",
                    )
                    if (
                        len(history_ids.ids)
                        < promotion_rule_id.months_retained_consultants
                    ):
                        active_sfm_promotion = False
                    else:
                        for history in history_ids:
                            if (
                                history.active_sfm_this_month
                                < promotion_rule_id.retained_consultants
                            ):
                                active_sfm_promotion = False
                    history_id.active_sfm_promotion = active_sfm_promotion

    def update_team_sales_manager(self, line):
        if line.consultant_id.id != line.payin_sheet_id.manager_id.id:
            history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "=", line.payin_sheet_id.payin_date),
                    ("employee_id", "=", line.consultant_id.manager_id.id),
                ]
            )
            if not history_id:
                history_id = self.env["bb.payin.history"].create(
                    {
                        "payin_date": line.payin_sheet_id.payin_date,
                        "employee_id": line.consultant_id.manager_id.id,
                        "active_status": line.consultant_id.manager_id.active_status,
                        "current_job_id": line.consultant_id.manager_id.genealogy,
                        "manager_code": line.consultant_id.manager_id.sales_force_code,
                        "distributor_code": line.consultant_id.manager_id.related_distributor_id.sales_force_code,
                        "manager_id": line.consultant_id.manager_id.manager_id.id,
                    }
                )
            history_id.active_status = line.consultant_id.manager_id.active_status
            history_id.team_bbb_sales += line.bb_brand_total
            history_id.team_puer_sales += line.puer_brand_total
            if line.sub_total != 0:
                history_id.active_sfm_this_month += 1
            team_promoted = 0
            if line.consultant_id.genealogy in ["manager", "prospective_distributor"]:
                previous_history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.manager_id.id),
                    ],
                    order="payin_date desc",
                    limit=1,
                )
                if previous_history_id:
                    history_id.team_promoted = previous_history_id.team_promoted

    def update_personal_and_team_sales(
        self, line, dates_to_exclude, promotion_rule_id, history_id
    ):
        # date_sale = date_sale - relativedelta(months=+self.date_sale)
        history_ids = self.env["bb.payin.history"].search(
            [
                ("payin_date", "<=", line.payin_sheet_id.payin_date),
                ("employee_id", "=", line.consultant_id.id),
                ("payin_date", "not in", dates_to_exclude),
            ],
            limit=promotion_rule_id.sales_month,
            order="payin_date desc",
        )
        personal_sales_promotion = True
        team_sales_promotion = True
        if len(history_ids.ids) < promotion_rule_id.sales_month:
            personal_sales_promotion = False
            team_sales_promotion = False
        else:
            for history in history_ids:
                # Updating personal
                if (
                    history.personal_bbb_sale + history.personal_puer_sale
                    < promotion_rule_id.own_sales_value
                ):
                    personal_sales_promotion = False

                # Update team sales
                # if history.personal_bbb_sale + history.personal_puer_sale < promotion_rule_id.own_sales_value:
                if (
                    history.team_bbb_sales + history.team_puer_sales
                    < promotion_rule_id.team_sales_value
                ):
                    team_sales_promotion = False
            history_id.team_sales_promotion = team_sales_promotion
            history_id.personal_sales_promotion = personal_sales_promotion

    def update_personal_sales_fields_for_the_current_sfm(self, line, history_id):
        history_id.active_status = line.consultant_id.active_status
        history_id.personal_bbb_sale = line.bb_brand_total
        history_id.personal_puer_sale = line.puer_brand_total
        if line.consultant_id.genealogy in ["manager", "prospective_distributor"]:
            history_id.team_bbb_sales += line.bb_brand_total
            history_id.team_puer_sales += line.puer_brand_total
        team_promoted = 0
        if line.consultant_id.genealogy in ["manager", "prospective_distributor"]:
            previous_history_id = self.env["bb.payin.history"].search(
                [
                    ("payin_date", "<", line.payin_sheet_id.payin_date),
                    ("employee_id", "=", line.consultant_id.id),
                ],
                order="payin_date desc",
                limit=1,
            )
            if previous_history_id:
                history_id.team_promoted = previous_history_id.team_promoted

        date = line.payin_sheet_id.payin_date.replace(month=1)
        dates_to_exclude = []
        promotion_rule_id = self.env["promotion.rules"].search(
            [("current_genealogy_level", "=", line.consultant_id.genealogy)], limit=1
        )
        for month in promotion_rule_id.months_to_exclude_ids:
            if date > line.payin_sheet_id.payin_date:
                date = date.replace(year=date.year - 1)
            dates_to_exclude.append(date)

        return dates_to_exclude, promotion_rule_id

    def get_history_id(self, line):
        history_id = self.env["bb.payin.history"].search(
            [
                ("payin_date", "=", line.payin_sheet_id.payin_date),
                ("employee_id", "=", line.consultant_id.id),
            ]
        )
        if not history_id:
            team_promoted = 0
            if line.consultant_id.genealogy in ["manager", "prospective_distributor"]:
                previous_history_id = self.env["bb.payin.history"].search(
                    [
                        ("payin_date", "<", line.payin_sheet_id.payin_date),
                        ("employee_id", "=", line.consultant_id.id),
                    ],
                    order="payin_date desc",
                    limit=1,
                )
                if previous_history_id:
                    team_promoted = previous_history_id.team_promoted
            history_id = self.env["bb.payin.history"].create(
                {
                    "payin_date": line.payin_sheet_id.payin_date,
                    "employee_id": line.consultant_id.id,
                    "team_promoted": team_promoted,
                    "active_status": line.consultant_id.active_status,
                    "current_job_id": line.consultant_id.genealogy,
                    "manager_code": line.consultant_id.manager_id.sales_force_code,
                    "distributor_code": line.consultant_id.related_distributor_id.sales_force_code,
                    "manager_id": line.consultant_id.manager_id.id,
                }
            )

        return history_id

    def update_sold_consultant_fields(self, line, count):
        # If consultant has sales history
        if line.sub_total != 0:
            count += 1
            line.consultant_id.last_sale_date2 = line.consultant_id.last_sale_date
            line.consultant_id.last_sale_date = line.payin_sheet_id.payin_date
            line.consultant_id.write({"active_status": "active1"})
            if not line.consultant_id.first_sale_date:
                line.consultant_id.first_sale_date = line.payin_sheet_id.payin_date
                if line.consultant_id.genealogy == "potential_consultant":
                    line.consultant_id.genealogy = "consultant"

        return count

    def captured_dist(self):
        count = 0
        for line in self.sheet_id_dist.payin_line_ids:
            if line.actual_sales != 0:
                count += 1
        self.sheet_id_dist.consultants_sales = count
        self.sheet_id_dist.state = "captured"
        self.sheet_id_dist.user_id = self.env.user.id
        self.sheet_id_dist.action_timer_stop()


class NotCapturedWizard(models.TransientModel):
    _name = "not.captured.wizard"

    sheet_id = fields.Many2one("bb.payin.sheet", "Pay-In Sheet")
    sheet_id_dist = fields.Many2one("payin.distributor", "Distributor Pay-In Sheet")
    message = fields.Char(
        "Message",
        default="You have not captured any pay-in sheet lines. Do you wish to continue?",
    )
    do_nothing = fields.Boolean("Do Nothing")

    def captured(self):
        view_id = self.env.ref("sales_force_support.capture_wizard_view").id
        capture_id = False
        if self.sheet_id:
            capture_id = self.env["capture.wizard"].create(
                {"sheet_id": self.sheet_id.id, "do_nothing": self.do_nothing}
            )
        else:
            view_id = self.env.ref("sales_force_support.capture_wizard_view_dist").id
            capture_id = self.env["capture.wizard"].create(
                {"sheet_id_dist": self.sheet_id_dist.id, "do_nothing": self.do_nothing}
            )
        return {
            "name": _("Confirm"),
            "type": "ir.actions.act_window",
            "res_model": "capture.wizard",
            "view_mode": "form",
            "view_type": "form",
            "views": [(view_id, "form")],
            "target": "new",
            "res_id": capture_id.id,
        }
