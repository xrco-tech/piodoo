# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    whatsapp_id = fields.Char(string='WhatsApp ID', index=True,
        help='Meta WhatsApp ID (usually same as MSISDN). Used for inbound '
             'partner matching.')
    telegram_id = fields.Char(index=True)
    chatbot_state = fields.Json(default=dict,
        help='Persistent bot variables (survives conversation close).')
    marketing_opt_out = fields.Boolean(
        help='Global no-contact-for-marketing flag.')
    conversation_ids = fields.One2many('comm.conversation', 'partner_id',
                                        string='Conversations')
    open_conversation_count = fields.Integer(
        compute='_compute_open_conversation_count')

    def _compute_open_conversation_count(self):
        Convo = self.env['comm.conversation']
        for p in self:
            p.open_conversation_count = Convo.search_count([
                ('partner_id', '=', p.id),
                ('lifecycle_state', 'in', ('open', 'waiting', 'handoff')),
            ])
