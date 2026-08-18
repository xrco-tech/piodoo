# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CommDialerAgentSession(models.Model):
    _name = 'comm.dialer.agent.session'
    _description = 'Dialer Agent Session'
    _order = 'user_id'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', 'Agent', required=True,
                              default=lambda s: s.env.user.id, ondelete='cascade')
    campaign_id = fields.Many2one('comm.dialer.campaign', 'Campaign',
                                  ondelete='set null',
                                  domain="[('state', '!=', 'done')]")
    state = fields.Selection([
        ('offline', 'Offline'),
        ('ready', 'Ready'),
        ('on_call', 'On Call'),
        ('wrap', 'Wrap-up'),
        ('paused', 'Paused'),
    ], default='offline', required=True)
    current_call_id = fields.Many2one('comm.voip.call', 'Current Call',
                                      ondelete='set null')
    # PJSIP endpoint to bridge answered calls to. Stored so the ARI bridge
    # service can filter Ready agents that actually have an endpoint.
    sip_ext = fields.Char(related='user_id.dialer_sip_ext', string='SIP Endpoint',
                          store=True, readonly=False)
    sip_secret = fields.Char(related='user_id.dialer_sip_secret', string='SIP Secret',
                             readonly=False)
    manual_answer = fields.Boolean(related='user_id.dialer_manual_answer',
                                   string='Manual Answer', readonly=False)
    last_state_change = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)',
         'This agent already has a dialer session.'),
    ]

    def _set_state(self, state):
        self.write({'state': state, 'last_state_change': fields.Datetime.now()})

    def action_ready(self):
        for s in self:
            if not s.campaign_id:
                raise UserError(_("Pick a campaign before going Ready."))
        self._set_state('ready')

    def action_pause(self):
        self._set_state('paused')

    def action_wrap(self):
        self._set_state('wrap')

    def action_offline(self):
        self.write({'state': 'offline', 'current_call_id': False,
                    'last_state_change': fields.Datetime.now()})

    @api.model
    def get_softphone_config(self):
        """Config for the current user's WebRTC softphone. Returns
        {'enabled': False} when nothing is provisioned yet, so the widget stays
        inert until an Asterisk account + the user's SIP endpoint exist."""
        user = self.env.user
        account = self.env['comm.voip.account'].search(
            [('provider', '=', 'asterisk'), ('active', '=', True)],
            order='is_default desc, sequence, id', limit=1)
        if not account or not account.sip_ws_url or not user.dialer_sip_ext:
            return {'enabled': False}
        return {
            'enabled': True,
            'ws_url': account.sip_ws_url,
            'domain': account.sip_domain or '',
            'ext': user.dialer_sip_ext,
            'secret': user.dialer_sip_secret or '',
            'ice': account.get_ice_servers(),
            'display': user.name,
            'manual_answer': user.dialer_manual_answer,
        }

    @api.model
    def open_my_session(self):
        """Return (creating if needed) the current user's session record —
        used by the 'My Dialer Console' menu action."""
        session = self.search([('user_id', '=', self.env.uid)], limit=1)
        if not session:
            session = self.create({'user_id': self.env.uid})
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Dialer Console'),
            'res_model': 'comm.dialer.agent.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'current',
        }
