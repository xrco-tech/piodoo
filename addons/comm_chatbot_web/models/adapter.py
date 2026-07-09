# -*- coding: utf-8 -*-
"""Web channel adapter.

The web channel is request/response — the widget POSTs a user message and
receives the bot's outbound in the same call. send() writes the outbound
into the interaction row and returns success; the HTTP controller reads
those interactions back to construct the widget's reply payload.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class WebAdapter:
    channel_code = 'web'

    def send(self, env, interaction, payload):
        """Web is polled via controller — nothing to push. The interaction row
        already carries rendered_body / options / media that the controller
        will serialise into the widget response."""
        return {'status': 'sent'}

    def receive(self, env, source_record):
        return {
            'wa_id': (source_record.session_token if hasattr(source_record,
                       'session_token') else ''),
            'body': '',
            'source_model': source_record._name,
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return f'web-{conversation.id}'

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        # Anyone with an open widget session can be reached
        return True


adapter_registry.register_adapter('web', WebAdapter)
