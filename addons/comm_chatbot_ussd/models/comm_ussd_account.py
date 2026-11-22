# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class CommUssdAccount(models.Model):
    _inherit = 'comm.ussd.account'

    flow_bot_id = fields.Many2one(
        'comm.bot', string='Runs the flow', ondelete='set null', index=True,
        help='When set, a session on this code runs this flow, whatever '
             'gateway it comes through. Empty: the code runs what it ran '
             'before (an older bot, or its own coded menu).')
    flow_previous_engine = fields.Char(
        help='The flow engine this account was set to before a flow was '
             'connected, so that disconnecting puts it back.')

    def _runs_now(self):
        """In words, what a dial on this code reaches today."""
        self.ensure_one()
        if self.flow_bot_id:
            return _("the flow “%s”", self.flow_bot_id.name)
        if 'flow_engine' in self._fields and self.flow_engine == 'chat2work':
            return _("Chat2Work's own menu")
        bot = self.env['whatsapp.chatbot'].sudo().search([
            ('channel', '=', 'ussd'), ('ussd_account_id', '=', self.id),
            ('status', '=', 'published')], limit=1)
        if bot:
            return _("the older bot “%s”", bot.name)
        return _("nothing")

    def _connect_flow(self, bot):
        """Make this code run `bot`. Another add-on may give an account its
        own engine (Chat2Work's coded menu); that choice is set aside while
        a flow is connected, and remembered."""
        self.ensure_one()
        if 'ussd' not in bot.channel_ids.mapped('code'):
            raise UserError(_("Tick USSD under Runs on for this flow first."))
        vals = {'flow_bot_id': bot.id}
        if 'flow_engine' in self._fields and self.flow_engine != 'chatbot':
            vals.update(flow_previous_engine=self.flow_engine, flow_engine='chatbot')
        self.write(vals)

    def _disconnect_flow(self):
        self.ensure_one()
        vals = {'flow_bot_id': False, 'flow_previous_engine': False}
        if 'flow_engine' in self._fields and self.flow_previous_engine:
            vals['flow_engine'] = self.flow_previous_engine
        self.write(vals)
