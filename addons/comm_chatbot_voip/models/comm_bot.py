# -*- coding: utf-8 -*-
from odoo import fields, models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    voip_account_id = fields.Many2one(
        'comm.voip.account', string='VoIP number', ondelete='set null',
        index=True, copy=False,
        help='The VoIP line this bot is the calling script for: the script an '
             'agent follows on calls over that line.')
