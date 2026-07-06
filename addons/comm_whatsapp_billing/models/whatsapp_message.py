# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    billing_event_ids = fields.One2many(
        'whatsapp.billing.event', 'message_id', string='Billing Events')

    # Convenience: does this incoming message open a 24h CS window?
    def _open_cs_window_if_incoming(self):
        FreeWindow = self.env['whatsapp.free.window']
        for msg in self:
            if not msg.is_incoming or not msg.wa_id:
                continue
            FreeWindow.open_window(
                account=msg.account_id,
                wa_id=msg.wa_id,
                partner=None,
                window_type='cs_24h',
                opened_at=msg.message_timestamp,
                source_message=msg,
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            records._open_cs_window_if_incoming()
        except Exception as e:
            _logger.warning('Failed to open CS window on message create: %s', e)
        # If Meta already gave us pricing on create, ledger it now.
        for msg in records:
            if msg.pricing_category:
                try:
                    self.env['whatsapp.billing.event']._create_from_message(msg)
                except Exception as e:
                    _logger.warning('Billing event on create failed for msg %s: %s',
                                    msg.id, e)
        return records

    def write(self, vals):
        res = super().write(vals)
        # Ledger fires when webhook status brings pricing_category, or when
        # message_status flips to a paid state.
        if not vals:
            return res
        triggers = {'pricing_category', 'message_status', 'status_timestamp'}
        if not (triggers & set(vals.keys())):
            return res
        BillingEvent = self.env['whatsapp.billing.event']
        for msg in self:
            if msg.pricing_category and msg.message_status in (
                    'sent', 'delivered', 'read'):
                try:
                    BillingEvent._create_from_message(msg)
                except Exception as e:
                    _logger.warning('Billing event on write failed for msg %s: %s',
                                    msg.id, e)
        return res
