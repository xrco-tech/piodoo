# -*- coding: utf-8 -*-
"""SMS-specific ingestion helpers on comm.billing.event.

Segment counting:
- GSM-7 default alphabet: 160 chars/segment single, 153 chars/segment when
  multipart
- UCS-2 (used when body contains non-GSM chars like emojis or many Latin
  extended chars): 70/67

We detect UCS-2 by falling back to it when the body has characters outside
the GSM-7 basic + extension tables.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENSION = set("|^€{}[~]\\")


def count_segments(body):
    if not body:
        return 0
    body = body or ''
    is_gsm7 = all(ch in GSM7_BASIC or ch in GSM7_EXTENSION for ch in body)
    if is_gsm7:
        length = len(body) + sum(1 for ch in body if ch in GSM7_EXTENSION)
        if length <= 160:
            return 1
        return (length + 152) // 153
    length = len(body)
    if length <= 70:
        return 1
    return (length + 66) // 67


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    sms_id = fields.Many2one('sms.sms', index=True, ondelete='set null')

    @api.model
    def _create_from_sms(self, sms):
        """Ingest an sms.sms once its state is 'sent' (delivered to carrier)."""
        if sms.state not in ('sent', 'delivered', 'read'):
            return self.browse()
        exists = self.search([('source_model', '=', 'sms.sms'),
                              ('source_id', '=', sms.id)], limit=1)
        if exists:
            return exists
        segments = count_segments(sms.body) or 1
        provider = 'Infobip'
        account_ref = False
        if 'account_id' in sms._fields and sms.account_id:
            provider = (sms.account_id.provider or 'Infobip').title()
            account_ref = sms.account_id.name

        return self.create({
            'event_date': fields.Datetime.now(),
            'channel': 'sms',
            'provider': provider,
            'account_ref': account_ref,
            'wa_id': sms.number,
            'direction': 'outbound',
            'category': 'sms_outbound_domestic',  # refined by country lookup
            'unit': 'segment',
            'unit_qty': segments,
            'source_model': 'sms.sms',
            'source_id': sms.id,
            'sms_id': sms.id,
        })
