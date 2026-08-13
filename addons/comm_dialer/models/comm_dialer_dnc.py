# -*- coding: utf-8 -*-
from odoo import fields, models


class CommDialerDnc(models.Model):
    _name = 'comm.dialer.dnc'
    _description = 'Do-Not-Call List'
    _order = 'create_date desc'
    _rec_name = 'number'

    number = fields.Char('Number', required=True, index=True)
    partner_id = fields.Many2one('res.partner', 'Contact', ondelete='set null')
    reason = fields.Char('Reason')

    _sql_constraints = [
        ('number_uniq', 'unique(number)',
         'This number is already on the Do-Not-Call list.'),
    ]
