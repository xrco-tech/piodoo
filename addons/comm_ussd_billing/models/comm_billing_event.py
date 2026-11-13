# -*- coding: utf-8 -*-
"""USSD-specific ingestion helpers on comm.billing.event."""
import logging
import math

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    ussd_session_id = fields.Many2one('whatsapp.chatbot.ussd.session',
        index=True, ondelete='set null')
    unit = fields.Selection(selection_add=[('ussd_20s', 'per 20 s of USSD session')],
                            ondelete={'ussd_20s': 'set default'})

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

        # Provider from the session's USSD account, else the bot's, if any
        provider = 'Africa\'s Talking'
        account_ref = False
        acc = session.ussd_account_id
        if not acc and session.chatbot_id and session.chatbot_id.ussd_account_id:
            acc = session.chatbot_id.ussd_account_id
        if acc:
            provider = dict(acc._fields['provider'].selection).get(acc.provider) or provider
            account_ref = acc.name

        unit, unit_qty = 'session', 1.0
        if acc and acc.provider == 'connect_mobile':
            # Connect Mobile bills per started 20 seconds of session time
            seconds = (fields.Datetime.now() - session.create_date).total_seconds()
            unit, unit_qty = 'ussd_20s', float(max(1, math.ceil(seconds / 20)))

        return self.create({
            'event_date': fields.Datetime.now(),
            'channel': 'ussd',
            'provider': provider,
            'account_ref': account_ref,
            'wa_id': session.phone_number,
            'carrier': session.carrier or False,
            'category': 'ussd_session',
            'unit': unit,
            'unit_qty': unit_qty,
            'source_model': 'whatsapp.chatbot.ussd.session',
            'source_id': session.id,
            'ussd_session_id': session.id,
        })
