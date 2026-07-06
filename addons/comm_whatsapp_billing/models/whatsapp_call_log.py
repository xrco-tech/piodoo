# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappCallLog(models.Model):
    _inherit = 'whatsapp.call.log'

    billing_event_ids = fields.One2many(
        'comm.billing.event',
        compute='_compute_billing_event_ids',
        string='Billing Events')

    def _compute_billing_event_ids(self):
        Event = self.env['comm.billing.event']
        for rec in self:
            rec.billing_event_ids = Event.search([
                ('source_model', '=', 'whatsapp.call.log'),
                ('source_id', '=', rec.id),
            ])

    def write(self, vals):
        res = super().write(vals)
        if 'call_status' not in vals and 'duration' not in vals:
            return res
        Event = self.env['comm.billing.event']
        for rec in self:
            if rec.call_status == 'ended' and rec.duration and rec.duration > 0:
                try:
                    Event._create_from_wa_call(rec)
                except Exception as e:
                    _logger.warning('Billing event on call write failed for %s: %s',
                                    rec.id, e)
        return res
