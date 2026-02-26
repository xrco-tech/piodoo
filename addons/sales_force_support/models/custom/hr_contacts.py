# -*- coding: utf-8 -*-
# Source: botle_buhle_custom
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class HrContacts(models.Model):
    _name = "hr.contacts"
    _description = "SF Member Contacts"

    member_id = fields.Many2one("sf.member", "SF Member")
    mobile = fields.Char("Mobile")
    email = fields.Char("Email")
    street = fields.Char("Street")
    city = fields.Char("City")
    suburb = fields.Char("Suburb")
    country_id = fields.Many2one("res.country", "Country")
    state_id = fields.Many2one("res.country.state", "Province")
