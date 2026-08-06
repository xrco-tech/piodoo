# -*- coding: utf-8 -*-

from odoo import api, fields, models


class Chat2workJob(models.Model):
    _name = 'chat2work.job'
    _description = 'Chat2Work Job Opening'
    _order = 'sequence, id'

    name = fields.Char('Role', required=True)
    location = fields.Char('Location')
    salary_text = fields.Char('Salary')
    requirements = fields.Char('Requirements')
    description = fields.Text('Description')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    slot_ids = fields.One2many('chat2work.interview.slot', 'job_id', 'Interview Slots')
    available_slot_count = fields.Integer('Available Slots', compute='_compute_available_slot_count')

    @api.depends('slot_ids.is_available')
    def _compute_available_slot_count(self):
        for rec in self:
            rec.available_slot_count = len(rec.slot_ids.filtered('is_available'))

    def ussd_label(self):
        """One-line label for the USSD job menu."""
        self.ensure_one()
        return '%s - %s' % (self.name, self.location) if self.location else (self.name or '')


class Chat2workInterviewSlot(models.Model):
    _name = 'chat2work.interview.slot'
    _description = 'Chat2Work Interview Slot'
    _order = 'start_datetime, id'

    job_id = fields.Many2one('chat2work.job', 'Job', required=True, ondelete='cascade')
    start_datetime = fields.Datetime('Start', required=True)
    capacity = fields.Integer('Capacity', default=1)
    active = fields.Boolean(default=True)
    booking_ids = fields.One2many('chat2work.interview.booking', 'slot_id')
    booked_count = fields.Integer('Booked', compute='_compute_availability', store=True)
    is_available = fields.Boolean('Available', compute='_compute_availability', store=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('booking_ids.state', 'capacity', 'active', 'start_datetime')
    def _compute_availability(self):
        now = fields.Datetime.now()
        for rec in self:
            booked = len(rec.booking_ids.filtered(lambda b: b.state == 'booked'))
            rec.booked_count = booked
            rec.is_available = bool(
                rec.active and booked < rec.capacity
                and (not rec.start_datetime or rec.start_datetime > now)
            )

    @api.depends('job_id.name', 'start_datetime')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.job_id.name or '', rec.ussd_label())

    def ussd_label(self):
        """Short slot label for the USSD slot menu, e.g. 'Mon 12 Aug 09:00'."""
        self.ensure_one()
        if not self.start_datetime:
            return 'TBD'
        local = fields.Datetime.context_timestamp(self, self.start_datetime)
        return local.strftime('%a %d %b %H:%M')


class Chat2workInterviewBooking(models.Model):
    _name = 'chat2work.interview.booking'
    _description = 'Chat2Work Interview Booking'
    _order = 'create_date desc'
    _rec_name = 'reference'

    reference = fields.Char(
        'Reference', required=True, copy=False, readonly=True,
        default=lambda s: s.env['ir.sequence'].next_by_code('chat2work.booking') or 'NEW')
    partner_id = fields.Many2one('res.partner', 'Candidate')
    phone = fields.Char('Phone')
    job_id = fields.Many2one('chat2work.job', 'Job', required=True, ondelete='restrict')
    slot_id = fields.Many2one('chat2work.interview.slot', 'Slot', required=True, ondelete='restrict')
    state = fields.Selection([
        ('booked', 'Booked'), ('cancelled', 'Cancelled'),
        ('completed', 'Completed'), ('no_show', 'No Show'),
    ], default='booked', required=True)
    channel = fields.Char('Booked Via', default='ussd')

    @api.model
    def book_slot(self, slot, partner=None, phone=None):
        """Create a booking for `slot`. Used by the USSD flow."""
        slot.ensure_one()
        return self.create({
            'slot_id': slot.id,
            'job_id': slot.job_id.id,
            'partner_id': partner.id if partner else False,
            'phone': phone or (partner and (partner.mobile or partner.phone)) or '',
        })
