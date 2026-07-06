# -*- coding: utf-8 -*-
"""Voice-specific ingestion helpers on comm.billing.event."""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    voice_session_id = fields.Many2one('comm.voice.call.session',
        index=True, ondelete='set null')

    @api.model
    def _create_from_voice_session(self, session):
        if not session.duration_seconds or session.duration_seconds <= 0:
            return self.browse()
        exists = self.search([
            ('source_model', '=', 'comm.voice.call.session'),
            ('source_id', '=', session.id),
        ], limit=1)
        if exists:
            return exists

        minutes = round((session.duration_seconds or 0) / 60.0, 4)
        # Contact phone: prefer partner mobile then phone
        wa_id = False
        if session.partner_id:
            wa_id = session.partner_id.mobile or session.partner_id.phone

        # Voice provider isn't modelled explicitly; use placeholder
        provider = 'SIP'
        return self.create({
            'event_date': session.ended_at or fields.Datetime.now(),
            'channel': 'voice',
            'provider': provider,
            'wa_id': wa_id,
            'partner_id': session.partner_id.id if session.partner_id else False,
            # Best guess without carrier info: outbound local mobile
            'direction': 'outbound',
            'category': 'voice_outbound_local_mobile',
            'unit': 'minute',
            'unit_qty': minutes,
            'source_model': 'comm.voice.call.session',
            'source_id': session.id,
            'voice_session_id': session.id,
        })
