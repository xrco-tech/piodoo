# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    communication_preference_ids = fields.One2many(
        'comm.partner.communication.preference', 'partner_id',
        string='Communication Preferences')
