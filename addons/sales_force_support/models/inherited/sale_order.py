# -*- coding: utf-8 -*-
# Source: bb_payin/models/sale_order.py  (consultant_id: hr.employee → sf.member)
from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = "sale.order"

    consultant_id = fields.Many2one("sf.member", string="Sales Force")
