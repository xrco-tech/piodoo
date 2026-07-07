# -*- coding: utf-8 -*-
"""Fork inbound whatsapp.message into the comm_chatbot executor for bots
owned by the new engine. Old engine handles the rest (grandfather)."""
import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Trigger = self.env['comm.bot.trigger']
        Executor = self.env['comm.chatbot.executor']
        for msg in records:
            if not msg.is_incoming:
                continue
            # Only route to new engine if a comm.bot.trigger matches
            trigger = Trigger.find_trigger('whatsapp', msg.message_body or '')
            if not trigger:
                # Also route existing open conversation → new engine
                partner_hint = msg.wa_id
                convo = self._find_open_new_engine_conversation(partner_hint)
                if not convo:
                    continue
            try:
                Executor.on_inbound(
                    channel_code='whatsapp',
                    source_model='whatsapp.message',
                    source_id=msg.id,
                    wa_id=msg.wa_id,
                    body=msg.message_body or '',
                    at=msg.message_timestamp,
                    external_session_id=msg.wa_id,
                )
            except Exception as e:
                _logger.warning('New-engine WA route failed for msg %s: %s',
                                msg.id, e)
        return records

    @api.model
    def _find_open_new_engine_conversation(self, wa_id):
        partner = self.env['res.partner'].sudo().search([
            '|', ('whatsapp_id', '=', wa_id), ('mobile', '=', wa_id),
        ], limit=1)
        if not partner:
            return self.env['comm.conversation']
        return self.env['comm.conversation'].search([
            ('partner_id', '=', partner.id),
            ('lifecycle_state', 'in', ('open', 'waiting')),
        ], limit=1)
