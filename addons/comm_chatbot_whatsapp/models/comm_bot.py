# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    whatsapp_account_id = fields.Many2one(
        'comm.whatsapp.account', string='WhatsApp number', ondelete='set null',
        index=True, copy=False,
        help='The WhatsApp number this bot answers on and sends from. A message '
             'starts the bot only when it comes in on this number. Empty: no '
             'message starts it.')

    @api.model
    def _connect_whatsapp_default(self):
        """Bots that already ran on WhatsApp, before a bot had a number of its
        own, ran on the default account. Keep them there."""
        account = self.env['comm.whatsapp.account'].sudo().get_default()
        if not account:
            return self.browse()
        bots = self.with_context(active_test=False).search([
            ('whatsapp_account_id', '=', False),
            '|', ('channel_ids.code', '=', 'whatsapp'),
            ('trigger_ids.channel_id.code', '=', 'whatsapp'),
        ])
        bots.write({'whatsapp_account_id': account.id})
        return bots
