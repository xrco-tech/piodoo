# -*- coding: utf-8 -*-
"""Reads and actions behind the softphone card: recent calls, contact search,
call activities and in-card transfer. All run as the signed-in agent, so the
own-calls record rule on comm.voip.call decides what they see."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

ANSWERED = ('in_progress', 'completed')
LIVE_TRANSFER = ('requested', 'active', 'consulting', 'completing', 'cancelling')


class CommDialerAgentSessionPhone(models.Model):
    _inherit = 'comm.dialer.agent.session'

    # ── Recent calls + contacts ──────────────────────────────────────────
    @api.model
    def _softphone_call_row(self, call):
        number = call._peer_number()
        return {
            'id': call.id,
            'name': call.partner_id.name or number or _("Unknown"),
            'number': number,
            'partner_id': call.partner_id.id or False,
            'direction': call.direction,
            'answered': call.state in ANSWERED,
            'duration': call.duration or 0,
            'at': fields.Datetime.to_string(call.start_time or call.create_date),
            'campaign': call.dialer_campaign_id.name or '',
        }

    @api.model
    def softphone_recent(self, search='', limit=40):
        """The agent's own calls, newest first; with a search term, also the
        contacts that match it. {'calls': [...], 'contacts': [...]}"""
        term = (search or '').strip()
        limit = max(1, min(int(limit or 40), 100))
        domain = [('agent_user_id', '=', self.env.uid)]
        contacts = []
        if term:
            domain += ['|', '|', ('partner_id.name', 'ilike', term),
                       ('from_number', 'ilike', term), ('to_number', 'ilike', term)]
            digits = re.sub(r'\D', '', term)
            who = [('name', 'ilike', term)]
            if len(digits) >= 3:
                who = ['|', '|'] + who + [('phone', 'like', digits), ('mobile', 'like', digits)]
            partners = self.env['res.partner'].search(
                ['&', '|', ('phone', '!=', False), ('mobile', '!=', False)] + who, limit=8)
            contacts = [{
                'id': p.id,
                'name': p.name or '',
                'number': p.mobile or p.phone,
            } for p in partners]
        calls = self.env['comm.voip.call'].search(domain, limit=limit)
        return {'calls': [self._softphone_call_row(c) for c in calls], 'contacts': contacts}

    # ── Activities ───────────────────────────────────────────────────────
    @api.model
    def softphone_activities(self, limit=40):
        """The agent's open call activities, most overdue first."""
        if 'mail.activity' not in self.env:
            return []
        activities = self.env['mail.activity'].search([
            ('user_id', '=', self.env.uid),
            ('activity_type_id.category', '=', 'phonecall'),
        ], order='date_deadline, id', limit=limit)
        today = fields.Date.context_today(self)
        rows = []
        for activity in activities:
            record = self.env[activity.res_model].browse(activity.res_id).exists() \
                if activity.res_model in self.env else False
            number = ''
            if record:
                holders = [record]
                if 'partner_id' in record._fields:
                    holders.append(record.partner_id)
                for holder in holders:
                    for field in ('mobile', 'phone'):
                        if not number and holder and field in holder._fields:
                            number = holder[field] or ''
            rows.append({
                'id': activity.id,
                'name': activity.res_name or (record and record.display_name) or _("Call"),
                'summary': activity.summary or activity.activity_type_id.name or '',
                'number': number,
                'due': fields.Date.to_string(activity.date_deadline),
                'late': bool(activity.date_deadline and activity.date_deadline < today),
                'today': activity.date_deadline == today,
                'res_model': activity.res_model,
                'res_id': activity.res_id,
            })
        return rows

    # ── Transfer ─────────────────────────────────────────────────────────
    @api.model
    def softphone_transfer_targets(self):
        """Other agents with a softphone, for the transfer sheet."""
        labels = dict(self._fields['state']._description_selection(self.env))
        sessions = self.search([('sip_ext', '!=', False), ('user_id', '!=', self.env.uid)])
        return [{
            'id': s.id,
            'name': s.user_id.name,
            'ext': s.sip_ext,
            'state': s.state,
            'state_label': labels.get(s.state, s.state),
        } for s in sessions]

    @api.model
    def softphone_transfer(self, call_id, target_session_id, mode='blind'):
        """Ask for the call to be handed to another agent. Blind hands over at
        once; attended puts the caller on hold while the two agents talk."""
        call = self._softphone_call(call_id)
        target = self.browse(int(target_session_id or 0)).exists()
        if not call or not target:
            return {'ok': False, 'message': _("Call or agent not found.")}
        try:
            transfer = self.env['comm.dialer.transfer']._request(call, target, mode)
        except UserError as err:
            return {'ok': False, 'message': err.args[0]}
        return {
            'ok': True,
            'id': transfer.id,
            'mode': transfer.mode,
            'state': transfer.state,
            'target': target.user_id.name,
            'message': _("Transferring to %s…", target.user_id.name),
        }

    @api.model
    def softphone_transfer_status(self, transfer_id):
        transfer = self.env['comm.dialer.transfer'].browse(int(transfer_id or 0)).exists()
        if not transfer:
            return {'state': 'failed', 'live': False, 'error': _("Transfer not found.")}
        return {'state': transfer.state, 'live': transfer.state in LIVE_TRANSFER,
                'error': transfer.error or ''}

    @api.model
    def softphone_transfer_decide(self, transfer_id, complete=True):
        """Finish an attended transfer: hand the caller over, or take them back."""
        transfer = self.env['comm.dialer.transfer'].browse(int(transfer_id or 0)).exists()
        if not transfer or transfer.requested_by != self.env.user:
            return self.softphone_transfer_status(transfer_id)
        if complete:
            transfer.action_complete()
        else:
            transfer.action_cancel()
        return self.softphone_transfer_status(transfer.id)
