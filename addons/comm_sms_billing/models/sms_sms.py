# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    billing_event_ids = fields.One2many(
        'comm.billing.event', 'sms_id', string='Billing Events')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for sms in records:
            if sms.state in ('sent', 'delivered'):
                try:
                    self.env['comm.billing.event']._create_from_sms(sms)
                except Exception as e:
                    _logger.warning('SMS billing on create failed for %s: %s',
                                    sms.id, e)
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'state' not in vals:
            return res
        Event = self.env['comm.billing.event']
        for sms in self:
            if sms.state in ('sent', 'delivered', 'read'):
                try:
                    Event._create_from_sms(sms)
                except Exception as e:
                    _logger.warning('SMS billing on write failed for %s: %s',
                                    sms.id, e)
        return res

    def _country_category_correction(self, event):
        """After the event lands, refine category by whether ZA vs intl.
        Called from comm_billing_event._create_from_sms already via country
        auto-fill in the base create()."""
        pass
