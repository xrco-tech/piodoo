# -*- coding: utf-8 -*-
# Source: botle_buhle_custom
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ResCommunication(models.Model):
    _name = "res.communication"
    _description = "Communication"

    stage_id = fields.Many2one(
        "sf.recruit.stage", "Status", related="recruit_id.stage_id"
    )
    recruit_id = fields.Many2one("sf.recruit", "Recruit")
    email_mobile = fields.Char("Email/Mobile")
    message = fields.Char("Message")
    campaign = fields.Char("Campaign")
    type = fields.Char("Type")
    suburb = fields.Char("Suburb")
    bound = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")], string="Inbound/Outbound"
    )
    date = fields.Date("Date")
    delivery_status = fields.Char("Delivery Status")
