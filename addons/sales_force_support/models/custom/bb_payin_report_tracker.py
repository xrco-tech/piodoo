# -*- coding: utf-8 -*-
# Source: bb_payin
from odoo import models, fields, api, _
import datetime
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging


class CapturedPayinSheetReportTrack(models.Model):
    _name = "captured.payinsheet.report.track"
    _description = "Captured Payin Sheet Report Track"

    payin_ids = fields.Many2one("bb.payin.sheet", string="PayIn ID")
    print_state = fields.Selection(
        selection=[
            ("printed", "Printed"),
            ("reprinted", "Reprinted"),
        ],
        string="Print Status",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    print_count = fields.Integer(
        string="Print Count",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        default=0,
    )


class CapturedDistributorSummaryReportTrack(models.Model):
    _name = "captured.summary.report.track"
    _description = "Captured Summary Report Track"

    payin_ids = fields.Many2one("payin.distributor", string="Distributor Summary ID")
    print_state = fields.Selection(
        selection=[
            ("printed", "Printed"),
            ("reprinted", "Reprinted"),
        ],
        string="Print Status",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    print_count = fields.Integer(
        string="Print Count",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        default=0,
    )
