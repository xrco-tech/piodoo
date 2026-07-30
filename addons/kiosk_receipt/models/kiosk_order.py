# -*- coding: utf-8 -*-
from odoo import models, fields


class KioskOrder(models.Model):
    """A sale mirrored from a POS kiosk. Deliberately a standalone mirror, not a
    sale.order/pos.order -- it records what happened on the device without
    entangling Odoo's sales/accounting flows. Idempotent on `kiosk_ref`."""
    _name = 'kiosk.order'
    _description = 'Kiosk Order (synced from POS)'
    _order = 'sold_at desc'
    _rec_name = 'kiosk_ref'

    kiosk_ref = fields.Char(string='Kiosk Ref', index=True, required=True)
    sold_at = fields.Datetime(string='Sold At')
    subtotal = fields.Float(string='Subtotal')
    tip = fields.Float(string='Tip')
    total = fields.Float(string='Total')
    cash = fields.Float(string='Cash')
    card = fields.Float(string='Card')
    item_count = fields.Integer(string='Items')
    staff_ref = fields.Char(string='Staff Ref')
    shift_ref = fields.Char(string='Shift Ref')
    checkout_id = fields.Char(string='Yoco Checkout')
    refund_id = fields.Char(string='Yoco Refund')
    lines_json = fields.Text(string='Line Items (JSON)')

    _sql_constraints = [
        ('kiosk_ref_uniq', 'unique(kiosk_ref)', 'This order has already been synced.'),
    ]
