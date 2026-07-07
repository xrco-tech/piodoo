# -*- coding: utf-8 -*-
"""USSD channel adapter.

USSD is synchronous: the incoming request from the provider MUST be answered
within seconds with a CON (continue) or END (terminate) response. Our
comm.chatbot.executor runs advance() inline; the adapter's `send` returns the
CON/END body directly rather than doing an outbound HTTP call.

To integrate with an existing USSD webhook: the webhook controller should
call `env['comm.chatbot.executor'].on_inbound(...)` and then read the last
outbound interaction's rendered_body to return to the provider.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class UssdAdapter:
    channel_code = 'ussd'

    def send(self, env, interaction, payload):
        """No outbound API call — record the payload; the webhook response
        handler pulls it as the CON/END body."""
        body = payload.get('body', '')
        options = payload.get('options', [])
        step = interaction.step_id

        if step and step.kind == 'end':
            prefix = 'END '
        elif step and step.kind == 'menu':
            prefix = 'CON '
        elif step and step.kind == 'input':
            prefix = 'CON '
        else:
            prefix = 'CON '

        # Options already numbered by degradation stage — body will contain them
        rendered = prefix + body
        interaction.rendered_body = rendered
        return {'status': 'sent'}

    def receive(self, env, source_record):
        return {
            'wa_id': source_record.phone_number,
            'body': (source_record.last_response or '').lstrip('*').rstrip('#'),
            'external_session_id': source_record.session_id,
            'source_model': 'whatsapp.chatbot.ussd.session',
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return None  # provider mints session ID

    def close_session(self, env, leg):
        return None  # provider ends the session

    def can_reach(self, env, partner):
        return bool(partner.mobile or partner.phone)


adapter_registry.register_adapter('ussd', UssdAdapter)
