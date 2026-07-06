# -*- coding: utf-8 -*-
"""WhatsApp-specific ingestion helpers on comm.billing.event."""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


META_CATEGORY_MAP = {
    'marketing':                     'marketing',
    'utility':                       'utility',
    'authentication':                'authentication',
    'authentication_international':  'auth_international',
    'service':                       'service',
    # Legacy conversation-based → nearest per-message equivalent
    'business_initiated':            'marketing',
    'user_initiated':                'service',
    'referral_conversion':           'service',
}


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    message_id = fields.Many2one('whatsapp.message', index=True, ondelete='set null')

    @api.model
    def _create_from_wa_message(self, message):
        if not message.pricing_category:
            return self.browse()
        exists = self.search([('source_model', '=', 'whatsapp.message'),
                              ('source_id', '=', message.id)], limit=1)
        if exists:
            return exists
        category = META_CATEGORY_MAP.get((message.pricing_category or '').lower())
        if not category:
            _logger.info('Unknown Meta pricing_category %r on message %s',
                         message.pricing_category, message.id)
            return self.browse()
        account_name = message.account_id.name if message.account_id else False
        return self.create({
            'event_date': (message.status_timestamp or message.message_timestamp
                           or fields.Datetime.now()),
            'channel': 'whatsapp',
            'provider': 'Meta',
            'account_ref': account_name,
            'wa_id': message.wa_id,
            'category': category,
            'unit': 'message',
            'unit_qty': 1.0,
            'direction': 'outbound' if not message.is_incoming else 'inbound',
            'source_model': 'whatsapp.message',
            'source_id': message.id,
            'message_id': message.id,
        })

    @api.model
    def _create_from_wa_call(self, call):
        if not call.duration or call.duration <= 0:
            return self.browse()
        exists = self.search([('source_model', '=', 'whatsapp.call.log'),
                              ('source_id', '=', call.id)], limit=1)
        if exists:
            return exists
        wa_id = (call.to_number if call.call_direction == 'outbound'
                 else call.from_number)
        minutes = round((call.duration or 0) / 60.0, 4)
        return self.create({
            'event_date': (call.end_timestamp or call.call_timestamp
                           or fields.Datetime.now()),
            'channel': 'whatsapp',
            'provider': 'Meta',
            'account_ref': call.account_id.name if call.account_id else False,
            'partner_id': call.partner_id.id if call.partner_id else False,
            'wa_id': wa_id,
            'direction': call.call_direction,
            'category': 'call_minute',
            'unit': 'minute',
            'unit_qty': minutes,
            'source_model': 'whatsapp.call.log',
            'source_id': call.id,
        })
