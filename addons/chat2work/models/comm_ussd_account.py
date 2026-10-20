# -*- coding: utf-8 -*-

from odoo import fields, models


class CommUssdAccount(models.Model):
    _inherit = 'comm.ussd.account'

    flow_engine = fields.Selection([
        ('chatbot', 'Chatbot Flow'),
        ('chat2work', 'Chat2Work USSD (spec v1.0)'),
    ], string='Flow Engine', default='chatbot', required=True,
        help="Chatbot Flow routes this service code to a published USSD chatbot. "
             "Chat2Work USSD runs the coded Chat2Work flow (profile / status / callback).")

    def action_open_chat2work_simulator(self):
        self.ensure_one()
        wizard = self.env['chat2work.ussd.simulator'].create({'account_id': self.id})
        return wizard._reopen()
