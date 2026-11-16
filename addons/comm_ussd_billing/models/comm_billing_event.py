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

        # The provider is whoever runs the code that was dialled.
        Account = self.env['comm.ussd.account'].sudo()
        acc = Account.find_for_service_code(session.service_code or '')
        provider = dict(Account._fields['provider'].selection).get(acc.provider) if acc else False
        account_ref = acc.name if acc else session.service_code

        # Charged by time. The gateway's own figure for the length
        # is used when the end-of-session notice carries one.
        seconds = self.env.context.get('ussd_seconds')
        if not seconds and session.create_date:
            seconds = (fields.Datetime.now() - session.create_date).total_seconds()

        return self.create({
            'event_date': fields.Datetime.now(),
            'channel': 'ussd',
            'provider': provider,
            'account_ref': account_ref,
            'wa_id': session.phone_number,
            'category': 'ussd_session',
            'unit': 'block',
            'unit_qty': 1.0,
            'duration_seconds': seconds or 0.0,
            'service_code': session.service_code,
            'source_model': 'whatsapp.chatbot.ussd.session',
            'source_id': session.id,
            'ussd_session_id': session.id,
        })
