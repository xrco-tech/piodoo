# -*- coding: utf-8 -*-
from odoo import fields, models


class CommBillingRate(models.Model):
    _inherit = 'comm.billing.rate'

    unit = fields.Selection(selection_add=[('ussd_20s', 'per 20 s of USSD session')],
                            ondelete={'ussd_20s': 'set default'})
