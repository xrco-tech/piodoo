# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class CommDialerContact(models.Model):
    _name = 'comm.dialer.contact'
    _description = 'Dialer Call-List Entry'
    _order = 'sequence, id'
    _rec_name = 'contact_label'

    campaign_id = fields.Many2one('comm.dialer.campaign', 'Campaign',
                                  required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', 'Contact', ondelete='set null')
    number = fields.Char('Number', required=True)
    contact_label = fields.Char('Name', compute='_compute_contact_label', store=True)

    state = fields.Selection([
        ('pending', 'Pending'),
        ('dialing', 'Dialing'),
        ('contacted', 'Contacted'),
        ('no_answer', 'No Answer'),
        ('busy', 'Busy'),
        ('failed', 'Failed'),
        ('retry', 'Retry'),
        ('dnc', 'Do Not Call'),
        ('done', 'Done'),
    ], default='pending', required=True, index=True)

    attempts = fields.Integer(default=0)
    last_attempt = fields.Datetime()
    next_attempt = fields.Datetime(help="Earliest time this row is eligible for a retry.")
    last_disposition_id = fields.Many2one('comm.disposition', 'Last Disposition')
    call_ids = fields.One2many('comm.voip.call', 'dialer_contact_id', 'Calls')
    call_count = fields.Integer(compute='_compute_call_count')
    notes = fields.Text()

    @api.depends('partner_id.name', 'number')
    def _compute_contact_label(self):
        for r in self:
            r.contact_label = (r.partner_id.name or r.number or 'Contact')

    def _compute_call_count(self):
        for r in self:
            r.call_count = len(r.call_ids)

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and not self.number:
            self.number = self.partner_id.mobile or self.partner_id.phone

    def _is_dnc(self):
        self.ensure_one()
        if not self.number:
            return False
        return bool(self.env['comm.dialer.dnc'].sudo().search_count(
            [('number', '=', self.number)]))

    def _originate(self, campaign, agent):
        """Create the outgoing call leg through the provider (stub) and mark the
        row as dialing. Returns the comm.voip.call record."""
        self.ensure_one()
        if self._is_dnc():
            self.state = 'dnc'
            return self.env['comm.voip.call']
        account = campaign.account_id
        call = self.env['comm.voip.call'].create({
            'account_id': account.id,
            'partner_id': self.partner_id.id or False,
            'direction': 'outgoing',
            'from_number': account.caller_id or '',
            'to_number': self.number,
            'state': 'queued',
            'start_time': fields.Datetime.now(),
            'dialer_contact_id': self.id,
        })
        result = account.originate(self.number, from_number=account.caller_id)
        if result.get('external_id'):
            call.external_id = result['external_id']
        self.write({
            'state': 'dialing',
            'attempts': self.attempts + 1,
            'last_attempt': fields.Datetime.now(),
        })
        if agent:
            agent.write({'state': 'on_call', 'current_call_id': call.id})
        return call

    def register_result(self, outcome, disposition=None):
        """Progress the row from a provider webhook or an agent wrap-up.

        ``outcome`` is one of: contacted / completed / no_answer / busy /
        failed / dnc. ``disposition`` is an optional comm.disposition record.
        """
        self.ensure_one()
        campaign = self.campaign_id
        vals = {'last_attempt': fields.Datetime.now()}
        if disposition:
            vals['last_disposition_id'] = getattr(disposition, 'id', disposition)

        if outcome in ('contacted', 'completed'):
            vals['state'] = 'contacted'
        elif outcome in ('no_answer', 'busy', 'failed'):
            if self.attempts >= campaign.max_attempts:
                vals['state'] = 'failed'
            else:
                vals['state'] = 'retry'
                vals['next_attempt'] = fields.Datetime.now() + timedelta(
                    hours=campaign.retry_gap_hours)
        elif outcome == 'dnc':
            vals['state'] = 'dnc'
            if self.number and not self._is_dnc():
                self.env['comm.dialer.dnc'].sudo().create({
                    'number': self.number,
                    'partner_id': self.partner_id.id or False,
                    'reason': 'Requested during dialer call',
                })
        self.write(vals)
