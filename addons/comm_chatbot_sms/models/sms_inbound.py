# -*- coding: utf-8 -*-
"""Every inbound SMS goes into the sender's UCX conversation, whether or not a
chatbot picks it up, so replies to our SMS are never lost."""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OPEN_STATES = ('open', 'waiting', 'handoff')


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model
    def _comm_record_inbound(self, partner, number, body, provider_message_id=None, to_number=None):
        super()._comm_record_inbound(partner, number, body, provider_message_id, to_number)
        if not partner:
            return False
        channel = self.env.ref('comm_chatbot.channel_sms', raise_if_not_found=False)
        if not channel:
            return False
        Conversation = self.env['comm.conversation'].sudo()
        conversation = Conversation.search([
            ('partner_id', '=', partner.id), ('lifecycle_state', 'in', OPEN_STATES),
        ], order='last_activity_at desc', limit=1) or Conversation.create({
            'partner_id': partner.id,
            'primary_channel_id': channel.id,
        })
        interaction = self.env['comm.interaction'].sudo().create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'direction': 'inbound',
            'at': fields.Datetime.now(),
            'raw_body': body or '',
            'rendered_body': body or '',
            'status': 'received',
        })
        conversation.touch()
        return interaction
