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

    def connections(self, env, bot):
        """The USSD codes that run this bot."""
        accounts = env['comm.ussd.account'].sudo().search([('flow_bot_id', '=', bot.id)])
        providers = dict(env['comm.ussd.account']._fields['provider'].selection)
        if not accounts:
            return [{'ok': False, 'text': 'No USSD code runs this flow yet. '
                     'Connect one below.'}]
        return [{'ok': True, 'text': 'Dialling %s reaches this flow (%s, %s).'
                 % (a.service_code or 'no code set', a.name, providers.get(a.provider, a.provider))}
                for a in accounts]

    def connect_options(self, env, bot):
        """The USSD codes this bot could run, and what each runs today."""
        return [{
            'id': a.id,
            'label': '%s  %s' % (a.service_code or '(no code)', a.name),
            'runs': a._runs_now(),
            'connected': a.flow_bot_id == bot,
        } for a in env['comm.ussd.account'].sudo().search([])]

    def connect(self, env, bot, option_id, on):
        account = env['comm.ussd.account'].sudo().browse(option_id).exists()
        if not account:
            return
        if on:
            account._connect_flow(bot)
        elif account.flow_bot_id == bot:
            account._disconnect_flow()

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
