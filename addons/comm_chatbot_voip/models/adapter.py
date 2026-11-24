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

    connect_noun = 'number'

    def connections(self, env, bot):
        """The VoIP line this bot is the calling script for."""
        lines = []
        account = bot.sudo().voip_account_id
        if account:
            lines.append({'ok': True, 'text': 'The calling script for calls on %s.' % account.name,
                          'name': account.name, 'address': account.caller_id or '',
                          'model': account._name, 'res_id': account.id,
                          'option_id': account.id})
        elif env['comm.voip.account'].sudo().search_count([]):
            lines.append({'ok': False, 'text': 'No VoIP number is set for this '
                          'script yet.'})
        else:
            lines.append({'ok': False, 'text': 'No VoIP account is set up.'})
        lines.append({'ok': False, 'text': 'The softphone does not open a flow '
                      'as the script during a call yet. This marks which line '
                      'the script is for.'})
        return lines

    def connect_options(self, env, bot):
        """The VoIP lines this bot could be the script for."""
        return [{
            'id': a.id,
            'label': '%s  %s' % (a.caller_id or '(no number)', a.name),
            'name': a.name,
            'code': a.caller_id or '',
            'runs': '',
            'ask_on': 'This flow will be marked as the calling script for calls '
                      'on %s. The softphone does not open it by itself yet.'
                      % (a.caller_id or a.name),
            'ask_off': 'This flow will no longer be marked as the script for %s.'
                       % (a.caller_id or a.name),
            'connected': a == bot.sudo().voip_account_id,
        } for a in env['comm.voip.account'].sudo().search([])]

    def connect(self, env, bot, option_id, on):
        account = env['comm.voip.account'].sudo().browse(option_id).exists()
        if not account:
            return
        if on:
            bot.sudo().voip_account_id = account
        elif bot.sudo().voip_account_id == account:
            bot.sudo().voip_account_id = False

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
