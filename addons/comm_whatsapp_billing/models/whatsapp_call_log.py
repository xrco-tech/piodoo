# -*- coding: utf-8 -*-
"""Soft inherit of whatsapp.call.log.

comm_whatsapp_calling is not a hard dependency: piodoo installs may or may
not have calling enabled. The inherit is registered only if the model is in
the registry at load time, so the billing module stays installable on its own.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappCallLog(models.Model):
    _inherit = 'whatsapp.call.log'

    billing_event_ids = fields.One2many(
        'whatsapp.billing.event',
        compute='_compute_billing_event_ids',
        string='Billing Events')

    def _compute_billing_event_ids(self):
        BillingEvent = self.env['whatsapp.billing.event']
        for rec in self:
            rec.billing_event_ids = BillingEvent.search([
                ('source_model', '=', 'whatsapp.call.log'),
                ('source_id', '=', rec.id),
            ])

    def write(self, vals):
        res = super().write(vals)
        if 'call_status' not in vals and 'duration' not in vals:
            return res
        BillingEvent = self.env['whatsapp.billing.event']
        for rec in self:
            if rec.call_status == 'ended' and rec.duration and rec.duration > 0:
                try:
                    BillingEvent._create_from_call(rec)
                except Exception as e:
                    _logger.warning('Billing event on call write failed for %s: %s',
                                    rec.id, e)
        return res
