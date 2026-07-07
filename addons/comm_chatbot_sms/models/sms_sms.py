# -*- coding: utf-8 -*-
"""Route inbound SMS into the comm_chatbot executor when a trigger matches.

comm_sms writes sms.sms records for inbound too (via its Infobip webhook
controller); we hook create() to fork routing.
"""
import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Executor = self.env['comm.chatbot.executor']
        Trigger = self.env['comm.bot.trigger']
        for sms in records:
            # Only consider inbound: comm_sms uses state='received' or similar.
            # If we can't tell, look for state != 'outgoing' / 'sent'.
            state = getattr(sms, 'state', '') or ''
            if state in ('outgoing', 'sent', 'process', 'canceled'):
                continue
            trigger = Trigger.find_trigger('sms', sms.body or '')
            if not trigger:
                continue
            try:
                Executor.on_inbound(
                    channel_code='sms',
                    source_model='sms.sms',
                    source_id=sms.id,
                    wa_id=sms.number,
                    body=sms.body or '',
                    external_session_id=sms.number,
                )
            except Exception as e:
                _logger.warning('New-engine SMS route failed for sms %s: %s',
                                sms.id, e)
        return records
