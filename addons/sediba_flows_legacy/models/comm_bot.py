# -*- coding: utf-8 -*-
from odoo import fields, models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    legacy_chatbot_id = fields.Many2one(
        'whatsapp.chatbot', string='Brought over from', ondelete='set null',
        index=True, copy=False,
        help='The older bot this flow was copied from.')
    import_notes = fields.Text(
        copy=False,
        help='What was and was not carried over, one line each.')
