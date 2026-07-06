# -*- coding: utf-8 -*-
"""USSD-specific ingestion helpers on comm.billing.event."""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    ussd_session_id = fields.Many2one('whatsapp.chatbot.ussd.session',
        index=True, ondelete='set null')

    @api.model
    def _create_from_ussd_session(self, session):
        if session.outcome == 'open':
            return self.browse()
        exists = self.search([
            ('source_model', '=', 'whatsapp.chatbot.ussd.session'),
            ('source_id', '=', session.id),
        ], limit=1)
        if exists:
            return exists

        # Provider from the linked chatbot's ussd account, if any
        provider = 'Africa\'s Talking'
        account_ref = False
        chatbot = getattr(session, 'chatbot_id', False)
        if chatbot and 'ussd_account_id' in chatbot._fields and chatbot.ussd_account_id:
            acc = chatbot.ussd_account_id
            provider = (acc.provider or provider).replace('_', ' ').title()
            account_ref = acc.name

        return self.create({
            'event_date': fields.Datetime.now(),
            'channel': 'ussd',
            'provider': provider,
            'account_ref': account_ref,
            'wa_id': session.phone_number,
            'category': 'ussd_session',
            'unit': 'session',
            'unit_qty': 1.0,
            'source_model': 'whatsapp.chatbot.ussd.session',
            'source_id': session.id,
            'ussd_session_id': session.id,
        })
