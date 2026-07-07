# -*- coding: utf-8 -*-
"""Voice channel adapter (stub).

Voice is real-time: TTS out, STT/DTMF in. Wiring to an actual voice provider
(SIP trunk, cloud PBX, WA Business Calling) is provider-specific. This
adapter records the outbound rendered_body for now; a follow-up module will
patch send() to invoke the actual TTS/streaming pipeline.

Streaming: adapter declares supports_streaming via comm.channel; the LLM
step's send path checks this and streams tokens through when true.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class VoiceAdapter:
    channel_code = 'voice'

    def send(self, env, interaction, payload):
        body = payload.get('body', '')
        options = payload.get('options', [])
        # DTMF prompt suffix if there are options
        if options:
            keys = ', '.join(f'{i+1} for {o["label"]}'
                             for i, o in enumerate(options))
            body = f'{body}\n(Press {keys})'
        interaction.rendered_body = body
        # TODO: hand off to TTS pipeline
        _logger.info('Voice adapter send (stub) — conversation %s: %r',
                     interaction.conversation_id.id, body[:80])
        return {'status': 'sent'}

    def receive(self, env, source_record):
        # comm.voice.call.session doesn't carry inbound text on its own — the
        # STT/DTMF pipeline needs to hook here. Placeholder.
        return {
            'wa_id': source_record.partner_id.mobile if source_record.partner_id else '',
            'body': (source_record.session_state or {}).get('last_input', ''),
            'external_session_id': str(source_record.id),
            'source_model': 'comm.voice.call.session',
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return None

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        return bool(partner.mobile)


adapter_registry.register_adapter('voice', VoiceAdapter)
