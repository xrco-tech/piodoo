# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    sms_account_id = fields.Many2one(
        'comm.sms.account', string='SMS sender', ondelete='set null',
        index=True, copy=False,
        help='The SMS account this bot sends from. Empty: the default account.')

    @api.model
    def _connect_sms_default(self):
        """Bots that already ran on SMS sent from the default account. Keep
        them on it, now that a bot has an account of its own."""
        account = self.env['comm.sms.account'].sudo().get_default()
        if not account:
            return self.browse()
        bots = self.with_context(active_test=False).search([
            ('sms_account_id', '=', False), ('channel_ids.code', '=', 'sms')])
        bots.write({'sms_account_id': account.id})
        return bots
