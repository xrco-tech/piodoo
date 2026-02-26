# -*- coding: utf-8 -*-
# Source: bbb_sales_force_genealogy/models/res_country.py
from odoo import models, fields


class ResCountry(models.Model):
    _inherit = "res.country"

    min_digit = fields.Integer(string="Minimum Phone Digit")
    max_digit = fields.Integer(string="Maximum Phone Digit")
