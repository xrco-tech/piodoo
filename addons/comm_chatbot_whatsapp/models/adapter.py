# -*- coding: utf-8 -*-
"""WhatsApp channel adapter.

Registers with comm_chatbot's adapter registry at module load. Adapter is a
plain Python class (not an Odoo model) — the registry maps 'whatsapp' →
WhatsappAdapter.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class WhatsappAdapter:
    channel_code = 'whatsapp'

    def send(self, env, interaction, payload):
        """Send an outbound bot message via comm.whatsapp.account.

        payload = {'body', 'options', 'media', ...}
        Returns dict with status + source_model + source_id.
        """
        conversation = interaction.conversation_id
        wa_id = conversation.partner_id.whatsapp_id or conversation.partner_id.mobile
        if not wa_id:
            return {'status': 'failed', 'error': 'no wa_id on partner'}

        Account = env['comm.whatsapp.account'].sudo()
        account = Account.search([('active', '=', True)], limit=1)
        if not account:
            return {'status': 'failed', 'error': 'no active WhatsApp account'}

        body = payload.get('body', '')
        try:
            # Basic path: send text message. Interactive buttons/lists could be
            # added by inspecting payload['options'] and switching to interactive
            # message send when the account supports it.
            result = account.send_text_message(to=wa_id, text=body)
        except AttributeError:
            _logger.warning('comm.whatsapp.account.send_text_message missing — '
                            'falling back to whatsapp.message.create')
            result = {}

        return {
            'status': 'sent',
            'source_model': 'whatsapp.message',
            'source_id': (result or {}).get('id') or False,
        }

    def receive(self, env, message):
        """Convert an inbound whatsapp.message into canonical form."""
        return {
            'wa_id': message.wa_id,
            'body': message.message_body or '',
            'at': message.message_timestamp,
            'external_session_id': message.wa_id,
            'source_model': 'whatsapp.message',
            'source_id': message.id,
        }

    def open_session(self, env, conversation, partner):
        return partner.whatsapp_id or partner.mobile

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        return bool(partner.whatsapp_id or partner.mobile)


adapter_registry.register_adapter('whatsapp', WhatsappAdapter)
