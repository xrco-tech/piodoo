# -*- coding: utf-8 -*-
"""Adapter + tool registry.

Channel adapters and Python-executor tools register themselves at module load
time. The runtime looks them up by key.

Adapter contract (implement in a channel module):

    class MyAdapter:
        channel_code = 'sms'          # matches comm.channel.code
        capabilities = { ... }         # informational; DB row is authoritative

        def send(self, env, interaction, rendered_payload) -> dict:
            # Push outbound to the provider. Return dict with:
            #   { 'provider_message_id': str, 'status': str, 'error': str? }

        def receive(self, env, source_record) -> dict:
            # Parse an inbound source record into canonical form:
            #   { 'wa_id': str, 'body': str, 'attachments': [...], 'at': datetime,
            #     'external_session_id': str, 'partner_hint': str? }

        def open_session(self, env, conversation, partner) -> str:
            # Return external_session_id for a new leg.

        def close_session(self, env, leg) -> None:
            # Close the provider-side session (usually a no-op for async channels).

        def can_reach(self, env, partner) -> bool:
            # Whether the partner is reachable on this channel.
"""
from odoo import models, api

_ADAPTERS = {}
_PYTHON_TOOLS = {}


def register_adapter(adapter_key, adapter_cls):
    """Called at module load time by channel adapter modules."""
    _ADAPTERS[adapter_key] = adapter_cls


def get_adapter(adapter_key):
    return _ADAPTERS.get(adapter_key)


def register_python_tool(key, callable_):
    """For LLM step tools with executor_type='python'."""
    _PYTHON_TOOLS[key] = callable_


def get_python_tool(key):
    return _PYTHON_TOOLS.get(key)


def registered_adapters():
    return dict(_ADAPTERS)


class CommChatbotRegistry(models.AbstractModel):
    """Odoo-side helpers to reach the registry from a recordset context."""
    _name = 'comm.chatbot.registry'
    _description = 'Chatbot adapter/tool registry access'

    @api.model
    def get_adapter_for_channel(self, channel):
        if not channel or not channel.adapter_key:
            return None
        return get_adapter(channel.adapter_key)

    @api.model
    def get_adapter_by_code(self, code):
        channel = self.env['comm.channel'].get_by_code(code)
        return self.get_adapter_for_channel(channel)

    @api.model
    def get_python_tool(self, key):
        return get_python_tool(key)
