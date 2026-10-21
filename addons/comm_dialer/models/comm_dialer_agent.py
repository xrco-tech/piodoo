# -*- coding: utf-8 -*-
import re

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
            'secret': user.sudo().dialer_sip_secret or '',
            'ice': account.get_ice_servers(),
            'display': user.name,
            'manual_answer': user.dialer_manual_answer,
            'auto_record': account.auto_record,
        }

    @api.model
    def softphone_call_start(self, header_call_id=None, from_number='', to_number='',
                             direction='incoming'):
        """Resolve (bridge-created) or create the comm.voip.call for a softphone
        call, populating from/to/start/state. Returns the call id so the browser
        can attach a recording and close the record on hangup."""
        Call = self.env['comm.voip.call']
        if header_call_id:
            try:
                call = Call.browse(int(header_call_id))
            except (TypeError, ValueError):
                call = Call.browse()
            if call.exists():
                call = call.sudo()
                vals = {}
                if not call.agent_user_id:
                    vals['agent_user_id'] = self.env.uid
                if not call.start_time:
                    vals['start_time'] = fields.Datetime.now()
                if call.state in ('queued', 'ringing'):
                    vals['state'] = 'in_progress'
                if vals:
                    call.write(vals)
                return call.id
        account = self.env['comm.voip.account'].search(
            [('provider', '=', 'asterisk'), ('active', '=', True)],
            order='is_default desc, sequence, id', limit=1)
        call = Call.create({
            'account_id': account.id if account else False,
            'direction': direction,
            'from_number': from_number or '',
            'to_number': to_number or '',
            'state': 'in_progress',
            'start_time': fields.Datetime.now(),
            'agent_user_id': self.env.uid,
        })
        return call.id

    @api.model
    def softphone_call_end(self, call_id):
        """Close out a softphone call: end_time + state (duration auto-fills)."""
        try:
            call = self.env['comm.voip.call'].browse(int(call_id))
        except (TypeError, ValueError):
            return False
        if call.exists() and call.state not in ('completed', 'failed', 'cancelled'):
            call.write({'end_time': fields.Datetime.now(), 'state': 'completed'})
        return True

    # ── Campaign + call script (softphone) ───────────────────────────────
    # Mirrors the WhatsApp call popup: a call suggests the script of the
    # campaign the customer belongs to, the agent can pick/switch scripts, and
    # can add the customer to a campaign mid-call.

    @api.model
    def _softphone_call(self, call_id):
        try:
            call = self.env['comm.voip.call'].browse(int(call_id))
        except (TypeError, ValueError):
            return self.env['comm.voip.call']
        return call.exists()

    @api.model
    def _dialer_rows_for(self, partner, number):
        """Call-list rows (any campaign) for this customer, newest first."""
        domain = []
        if partner:
            domain = [('partner_id', '=', partner.id)]
        digits = re.sub(r'\D', '', number or '')
        if len(digits) >= 6:
            num_domain = [('number', 'like', digits[-9:])]
            domain = ['|'] + domain + num_domain if domain else num_domain
        if not domain:
            return self.env['comm.dialer.contact']
        return self.env['comm.dialer.contact'].search(domain, order='id desc')

    @api.model
    def softphone_call_context(self, call_id):
        """Campaign + suggested call script for a softphone call.

        Script resolution: the dialer campaign that placed the call, else the
        newest live dialer campaign the customer is on that has a script, else
        (when contact_centre is installed) their contact-centre campaign's
        voice script — the same fallback WhatsApp calls use."""
        call = self._softphone_call(call_id)
        if not call:
            return {}
        number = call._peer_number()
        partner = call.partner_id or call._match_partner(number)
        if partner and not call.partner_id:
            call.sudo().partner_id = partner
        rows = self._dialer_rows_for(partner, number).filtered(
            lambda r: r.campaign_id.active and r.campaign_id.state != 'done')
        campaign = call.dialer_campaign_id
        if not campaign:
            scripted = rows.filtered(lambda r: r.campaign_id.voice_chatbot_id)
            campaign = (scripted or rows)[:1].campaign_id
        chatbot = campaign.voice_chatbot_id
        if not chatbot and partner and 'contact.centre.contact' in self.env:
            cc_contact = self.env['contact.centre.contact'].sudo().search(
                [('partner_id', '=', partner.id)], limit=1)
            if cc_contact:
                chatbot = self.env['contact.centre.campaign'].sudo().search([
                    ('contact_ids', 'in', cc_contact.ids),
                    ('voice_chatbot_id', '!=', False),
                ], order='id desc', limit=1).voice_chatbot_id
        return {
            'call_id': call.id,
            'number': number,
            'partner_id': partner.id or False,
            'partner_name': partner.name or '',
            'partner_mobile': partner.mobile or partner.phone or number,
            'campaign_id': campaign.id or False,
            'campaign_name': campaign.name or '',
            'campaign_ids': rows.campaign_id.ids,
            'chatbot_id': chatbot.id or False,
            'chatbot_name': chatbot.name or '',
        }

    @api.model
    def softphone_campaign_options(self, call_id):
        """Open dialer campaigns for the 'Add to campaign' picker, flagging the
        ones this customer is already on."""
        call = self._softphone_call(call_id)
        already = set()
        if call:
            number = call._peer_number()
            partner = call.partner_id or call._match_partner(number)
            already = set(self._dialer_rows_for(partner, number).campaign_id.ids)
        campaigns = self.env['comm.dialer.campaign'].search([('state', '!=', 'done')])
        return [{
            'id': c.id,
            'name': c.name,
            'mode': c.mode,
            'state': c.state,
            'has_script': bool(c.voice_chatbot_id),
            'already': c.id in already,
        } for c in campaigns]

    @api.model
    def softphone_add_to_campaign(self, call_id, campaign_id):
        """Put the customer on this call into a dialer campaign's call list."""
        call = self._softphone_call(call_id)
        campaign = self.env['comm.dialer.campaign'].browse(int(campaign_id)).exists()
        if not call or not campaign:
            return {'ok': False, 'message': _("Call or campaign not found.")}
        number = call._peer_number()
        if not number:
            return {'ok': False, 'message': _("This call has no customer number.")}
        partner = call.partner_id or call._match_partner(number)
        if campaign in self._dialer_rows_for(partner, number).campaign_id:
            return {'ok': True, 'message': _("Already on %s.", campaign.name)}
        if self.env['comm.dialer.dnc'].sudo().search_count([('number', '=', number)]):
            return {'ok': False, 'message': _("%s is on the Do-Not-Call list.", number)}
        self.env['comm.dialer.contact'].create({
            'campaign_id': campaign.id,
            'partner_id': partner.id or False,
            'number': number,
            'notes': _("Added from a softphone call by %s.", self.env.user.name),
        })
        return {'ok': True, 'message': _("Added to %s.", campaign.name)}

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
