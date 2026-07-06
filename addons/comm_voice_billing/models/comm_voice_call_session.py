# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommVoiceCallSession(models.Model):
    _inherit = 'comm.voice.call.session'

    billing_event_ids = fields.One2many(
        'comm.billing.event', 'voice_session_id', string='Billing Events')

    def write(self, vals):
        res = super().write(vals)
        # Bill when the call actually ends (ended_at gets set) OR when
        # outcome transitions off 'open'.
        if 'ended_at' not in vals and 'outcome' not in vals:
            return res
        Event = self.env['comm.billing.event']
        for session in self:
            if session.ended_at and session.duration_seconds > 0:
                try:
                    Event._create_from_voice_session(session)
                except Exception as e:
                    _logger.warning('Voice billing on write failed for %s: %s',
                                    session.id, e)
        return res
