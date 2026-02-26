# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy

from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class InterviewDeclineReasons(models.Model):
    _name = "interview.decline.reasons"

    decline_reason = fields.Char("Decline Reason", tracking=True)
