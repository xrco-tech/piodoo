# -*- coding: utf-8 -*-

from odoo import api, fields, models


class CommVoipCall(models.Model):
    _name = 'comm.voip.call'
    _description = 'VoIP Call Log'
    _order = 'start_time desc, id desc'
    _rec_name = 'contact_display'

    account_id = fields.Many2one('comm.voip.account', 'VoIP Account',
                                 ondelete='set null', index=True)
    partner_id = fields.Many2one('res.partner', 'Contact', ondelete='set null')
    # Optional link into the omnichannel conversation timeline.
    conversation_id = fields.Many2one('comm.conversation', 'Conversation',
                                      ondelete='set null', index=True)

    direction = fields.Selection([
        ('incoming', 'Incoming'), ('outgoing', 'Outgoing'),
    ], default='outgoing', required=True)
    from_number = fields.Char('From')
    to_number = fields.Char('To')
    external_id = fields.Char('Provider Call ID', index=True,
                              help="The call id returned by the VoIP provider.")

    state = fields.Selection([
        ('queued', 'Queued'),
        ('ringing', 'Ringing'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('no_answer', 'No Answer'),
        ('busy', 'Busy'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='queued', index=True)

    start_time = fields.Datetime('Start')
    end_time = fields.Datetime('End')
    duration = fields.Integer('Duration (s)')
    duration_display = fields.Char('Duration', compute='_compute_duration_display')
    recording_url = fields.Char('Recording URL')
    notes = fields.Text('Notes')

    contact_display = fields.Char('Contact', compute='_compute_contact_display', store=True)

    @api.depends('duration')
    def _compute_duration_display(self):
        for rec in self:
            s = rec.duration or 0
            if s <= 0:
                rec.duration_display = '—'
            elif s < 60:
                rec.duration_display = '%ds' % s
            else:
                rec.duration_display = '%dm %ds' % (s // 60, s % 60)

    @api.depends('partner_id.name', 'from_number', 'to_number', 'direction')
    def _compute_contact_display(self):
        for rec in self:
            if rec.partner_id and rec.partner_id.name:
                rec.contact_display = rec.partner_id.name
            elif rec.direction == 'outgoing':
                rec.contact_display = rec.to_number or 'Unknown'
            else:
                rec.contact_display = rec.from_number or 'Unknown'
