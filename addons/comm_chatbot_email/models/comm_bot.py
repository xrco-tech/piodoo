# -*- coding: utf-8 -*-
from odoo import fields, models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    email_alias_id = fields.Many2one(
        'mail.alias', string='Email address', ondelete='set null',
        index=True, copy=False,
        help='Mail sent to this address starts the bot, and the bot replies '
             'from it. Empty: no email starts it.')
