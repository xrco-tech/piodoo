# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsappChatbotUssdSession(models.Model):
    _inherit = 'whatsapp.chatbot.ussd.session'

    billing_event_ids = fields.One2many(
        'comm.billing.event', 'ussd_session_id', string='Billing Events')

    def write(self, vals):
        res = super().write(vals)
        if 'outcome' not in vals:
            return res
        Event = self.env['comm.billing.event']
        for session in self:
            if session.outcome and session.outcome != 'open':
                try:
                    Event._create_from_ussd_session(session)
                except Exception as e:
                    _logger.warning('USSD billing on write failed for %s: %s',
                                    session.id, e)
        return res
