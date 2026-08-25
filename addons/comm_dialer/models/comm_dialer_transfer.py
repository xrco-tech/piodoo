# -*- coding: utf-8 -*-
"""VoIP call transfer — blind (attended to follow).

An agent on a live call picks a target agent; this creates a request row that
the dialer_ari service polls (like queued calls / barge requests). For a blind
transfer the service originates the target agent into the customer's existing
ARI bridge and drops the original agent — the customer is handed straight over.

Unlike WhatsApp calls (Meta = cold-transfer-only), VoIP runs through Asterisk,
so this can grow to attended (warm) transfer too — the 'attended' mode and the
extra states are stubbed here for that next increment.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommDialerTransfer(models.Model):
    _name = 'comm.dialer.transfer'
    _description = 'VoIP Call Transfer'
    _order = 'create_date desc'
    _rec_name = 'call_id'

    call_id = fields.Many2one(
        'comm.voip.call', 'Call', required=True, ondelete='cascade', index=True)
    requested_by = fields.Many2one(
        'res.users', 'Requested By', default=lambda self: self.env.user)
    mode = fields.Selection(
        [('blind', 'Blind'), ('attended', 'Attended')], default='blind', required=True)
    target_agent_session_id = fields.Many2one('comm.dialer.agent.session', 'To Agent')
    # What the service dials, and the target's session id for Odoo bookkeeping.
    target_endpoint = fields.Char('Target Endpoint')      # e.g. PJSIP/1002
    target_session_id = fields.Integer('Target Session')
    state = fields.Selection([
        ('requested', 'Requested'),
        ('active', 'Connecting'),      # blind: originating / attended: setting up consult
        ('consulting', 'Consulting'),  # attended: agent talking to the target, caller on hold
        ('completing', 'Completing'),  # attended: agent chose Complete
        ('cancelling', 'Cancelling'),  # attended: agent chose Cancel
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ], default='requested', index=True)
    error = fields.Char('Error')

    # ── Attended-transfer decisions (the service acts on the state change) ──
    def action_complete(self):
        for t in self:
            if t.mode == 'attended' and t.state in ('active', 'consulting'):
                t.state = 'completing'
        return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        for t in self:
            if t.mode == 'attended' and t.state in ('active', 'consulting'):
                t.state = 'cancelling'
        return {'type': 'ir.actions.act_window_close'}


class CommDialerTransferWizard(models.TransientModel):
    _name = 'comm.dialer.transfer.wizard'
    _description = 'Transfer Call'

    call_id = fields.Many2one('comm.voip.call', 'Call', required=True)
    source_session_id = fields.Many2one('comm.dialer.agent.session', 'Current Agent')
    mode = fields.Selection([
        ('blind', 'Blind — hand off immediately'),
        ('attended', 'Attended — consult first'),
    ], default='blind', required=True)
    target_agent_session_id = fields.Many2one(
        'comm.dialer.agent.session', 'Transfer to', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        call_id = res.get('call_id') or self.env.context.get('default_call_id')
        if call_id:
            call = self.env['comm.voip.call'].browse(call_id)
            if call.dialer_agent_session_id:
                res['source_session_id'] = call.dialer_agent_session_id.id
        return res

    def action_transfer(self):
        self.ensure_one()
        if self.call_id.state != 'in_progress':
            raise UserError(_("Only a call in progress can be transferred."))
        tgt = self.target_agent_session_id
        if not tgt.sip_ext:
            raise UserError(_("The chosen agent has no SIP endpoint."))
        xfer = self.env['comm.dialer.transfer'].create({
            'call_id': self.call_id.id,
            'mode': self.mode,
            'target_agent_session_id': tgt.id,
            'target_endpoint': 'PJSIP/%s' % tgt.sip_ext,
            'target_session_id': tgt.id,
        })
        if self.mode == 'attended':
            # Open the consult control panel — the caller goes on hold while the
            # agent talks to the target, then Complete or Cancel from here.
            return {
                'type': 'ir.actions.act_window',
                'name': _('Attended Transfer'),
                'res_model': 'comm.dialer.transfer',
                'res_id': xfer.id,
                'view_mode': 'form',
                'view_id': self.env.ref(
                    'comm_dialer.view_comm_dialer_transfer_consult_form').id,
                'target': 'new',
            }
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'type': 'success', 'title': _('Transferring'),
                'message': _('Blind transfer to %s — connecting…') % tgt.user_id.name,
                'sticky': False,
            },
        }
