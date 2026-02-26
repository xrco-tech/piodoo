# -*- coding: utf-8 -*-
# Source: bb_payin/models/purchase_order.py  (buyer_id: hr.employee → sf.member)
from odoo import models, fields


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    buyer_id = fields.Many2one("sf.member", string="Buyer")
    payin_line_id = fields.Many2one("bb.payin.sheet.line", string="Pay-In Ref")
