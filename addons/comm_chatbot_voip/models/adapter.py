# -*- coding: utf-8 -*-
"""VoIP channel adapter (stub).

VoIP is real-time and provider-specific (Infobip Voice / SIP trunk / Twilio /
etc.). This foundation registers the channel so it exists across the stack;
a follow-up module patches send()/receive() to place/receive real calls
through comm.voip.account credentials and log to comm.voip.call.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class VoipAdapter:
    channel_code = 'voip'

    def send(self, env, interaction, payload):
        # No provider wired yet — record the intended body for the timeline.
        body = payload.get('body', '')
        interaction.rendered_body = body
        _logger.info('VoIP adapter send (stub) — conversation %s: %r',
                     interaction.conversation_id.id if interaction.conversation_id else None,
                     (body or '')[:80])
        return {'status': 'sent'}

    def receive(self, env, source_record):
        # Inbound STT/DTMF/webhook pipeline hooks here once a provider is wired.
        return {
            'wa_id': getattr(source_record, 'from_number', '') or '',
            'body': '',
            'external_session_id': getattr(source_record, 'external_id', '') or '',
            'source_model': 'comm.voip.call',
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return None

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        return bool(partner.mobile or partner.phone)


adapter_registry.register_adapter('voip', VoipAdapter)
