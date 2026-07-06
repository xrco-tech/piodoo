# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    billing_event_ids = fields.One2many(
        'comm.billing.event', 'message_id', string='Billing Events')

    def _open_cs_window_if_incoming(self):
        FreeWindow = self.env['comm.billing.free.window']
        for msg in self:
            if not msg.is_incoming or not msg.wa_id:
                continue
            FreeWindow.open_window(
                account_ref=msg.account_id.name if msg.account_id else False,
                wa_id=msg.wa_id,
                window_type='cs_24h',
                opened_at=msg.message_timestamp,
                source_ref=f'whatsapp.message:{msg.id}',
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            records._open_cs_window_if_incoming()
        except Exception as e:
            _logger.warning('CS window open failed: %s', e)
        for msg in records:
            if msg.pricing_category:
                try:
                    self.env['comm.billing.event']._create_from_wa_message(msg)
                except Exception as e:
                    _logger.warning('Billing event on create failed for msg %s: %s',
                                    msg.id, e)
        return records

    def write(self, vals):
        res = super().write(vals)
        if not vals:
            return res
        triggers = {'pricing_category', 'message_status', 'status_timestamp'}
        if not (triggers & set(vals.keys())):
            return res
        Event = self.env['comm.billing.event']
        for msg in self:
            if msg.pricing_category and msg.message_status in (
                    'sent', 'delivered', 'read'):
                try:
                    Event._create_from_wa_message(msg)
                except Exception as e:
                    _logger.warning('Billing event on write failed for msg %s: %s',
                                    msg.id, e)
        return res
