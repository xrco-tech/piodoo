# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    """Kiosk customers sync into the real CRM (res.partner), keyed by the
    device-side id so they upsert instead of duplicating."""
    _inherit = 'res.partner'

    x_kiosk_ref = fields.Char(string='Kiosk Customer Ref', index=True)
