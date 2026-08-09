# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _send_sms(env, number, body):
    """Best-effort SMS via core sms.sms. Never raises — a failed/unconfigured
    SMS gateway must not break the booking/callback it confirms."""
    if not number:
        return False
    try:
        env['sms.sms'].sudo().create({
            'number': number, 'body': body, 'state': 'outgoing',
        })._send()
        return True
    except Exception as e:  # noqa: BLE001
        _logger.warning("chat2work: SMS to %s failed: %s", number, e)
        return False


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


class Chat2workCandidate(models.Model):
    _name = 'chat2work.candidate'
    _description = 'Chat2Work Candidate Profile'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char('Full Name', required=True)
    partner_id = fields.Many2one('res.partner', 'Contact')
    phone = fields.Char('Phone')
    location = fields.Char('Town / Area')
    field = fields.Selection([
        ('call_centre', 'Call Centre'),
        ('retail', 'Retail'),
        ('warehouse', 'Warehouse / Driver'),
        ('admin', 'Admin / General'),
        ('other', 'Other'),
    ], string='Field')
    registered_via = fields.Char('Registered Via', default='ussd')
    active = fields.Boolean(default=True)

    @api.model
    def upsert(self, partner=None, phone=None, name=None, location=None, field=None, registered_via='ussd'):
        """Create or update the candidate profile for this caller (matched by
        partner, then phone). Used by the USSD Register flow."""
        rec = self.env['chat2work.candidate']
        if partner:
            rec = self.search([('partner_id', '=', partner.id)], limit=1)
        if not rec and phone:
            rec = self.search([('phone', '=', phone)], limit=1)
        phone = phone or (partner and (partner.mobile or partner.phone)) or ''
        vals = {'registered_via': registered_via}
        if name:
            vals['name'] = name
        if location is not None:
            vals['location'] = location
        if field:
            vals['field'] = field
        if rec:
            rec.write(vals)
        else:
            vals.setdefault('name', name or 'Candidate')
            vals['partner_id'] = partner.id if partner else False
            vals['phone'] = phone
            rec = self.create(vals)
        # Keep the linked partner's name in sync with the registered name.
        if partner and name:
            partner.name = name
            if phone and not partner.mobile:
                partner.mobile = phone
        return rec


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
        """Create a booking for `slot` and SMS a confirmation. Used by USSD."""
        slot.ensure_one()
        booking = self.create({
            'slot_id': slot.id,
            'job_id': slot.job_id.id,
            'partner_id': partner.id if partner else False,
            'phone': phone or (partner and (partner.mobile or partner.phone)) or '',
        })
        booking._send_confirmation_sms()
        return booking

    def _send_confirmation_sms(self):
        for bk in self:
            number = bk.phone or (bk.partner_id and (bk.partner_id.mobile or bk.partner_id.phone)) or ''
            body = ("Chat2Work: interview booked. %s on %s. Ref %s. We'll SMS the address & reminders."
                    % (bk.job_id.name or '', bk.slot_id.ussd_label() if bk.slot_id else 'TBD', bk.reference))
            _send_sms(self.env, number, body)

    def action_cancel(self):
        """Cancel the booking(s). Used by the USSD flow."""
        self.write({'state': 'cancelled'})
        return True

    def reschedule(self, new_slot):
        """Move this booking to a different (available) slot + SMS the update."""
        self.ensure_one()
        new_slot.ensure_one()
        self.write({'slot_id': new_slot.id, 'job_id': new_slot.job_id.id})
        number = self.phone or (self.partner_id and (self.partner_id.mobile or self.partner_id.phone)) or ''
        _send_sms(self.env, number,
                  "Chat2Work: interview rescheduled to %s. Ref %s." % (new_slot.ussd_label(), self.reference))
        return True


class Chat2workCallbackRequest(models.Model):
    _name = 'chat2work.callback.request'
    _description = 'Chat2Work Callback Request'
    _order = 'create_date desc'
    _rec_name = 'phone'

    partner_id = fields.Many2one('res.partner', 'Contact')
    phone = fields.Char('Phone')
    candidate_id = fields.Many2one('chat2work.candidate', 'Candidate')
    state = fields.Selection([
        ('new', 'New'), ('in_progress', 'In Progress'),
        ('done', 'Done'), ('cancelled', 'Cancelled'),
    ], default='new', required=True)
    channel = fields.Char('Requested Via', default='ussd')
    notes = fields.Text('Notes')

    @api.model
    def request_callback(self, partner=None, phone=None, channel='ussd'):
        """Log a callback request for a caller. Used by the USSD flow."""
        phone = phone or (partner and (partner.mobile or partner.phone)) or ''
        cand = self.env['chat2work.candidate']
        if partner:
            cand = cand.search([('partner_id', '=', partner.id)], limit=1)
        if not cand and phone:
            cand = self.env['chat2work.candidate'].search([('phone', '=', phone)], limit=1)
        rec = self.create({
            'partner_id': partner.id if partner else False,
            'phone': phone,
            'candidate_id': cand.id if cand else False,
            'channel': channel,
        })
        _send_sms(self.env, phone,
                  "Chat2Work: thanks for your callback request. A consultant will call you within 1 business day.")
        return rec
