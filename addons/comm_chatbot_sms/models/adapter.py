# -*- coding: utf-8 -*-
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class SmsAdapter:
    channel_code = 'sms'

    def send(self, env, interaction, payload):
        conversation = interaction.conversation_id
        number = conversation.partner_id.mobile or conversation.partner_id.phone
        if not number:
            return {'status': 'failed', 'error': 'no mobile/phone on partner'}

        Sms = env['sms.sms'].sudo()
        body = payload.get('body', '')
        try:
            # comm.bot has no SMS account of its own, so pin the default one
            # (when there is one) for provider routing and billing.
            account = env['comm.sms.account'].get_default()
            sms = Sms.create({
                'partner_id': conversation.partner_id.id,
                'number': number,
                'body': body,
                'state': 'outgoing',
                'account_id': account.id or False,
            })
            sms.send()
        except Exception as e:
            _logger.warning('SMS send failed: %s', e)
            return {'status': 'failed', 'error': str(e)}

        return {'status': 'sent', 'source_model': 'sms.sms',
                'source_id': sms.id}

    def connections(self, env, bot):
        """The SMS sender this bot sends from. Replies are not wired yet."""
        lines = []
        account = env['comm.sms.account'].sudo().get_default()
        if account:
            sender = account.sender_id or 'no sender name or number on the account'
            lines.append({'ok': True, 'text': 'Sends from %s (%s). Every flow '
                          'uses the default SMS account.' % (account.name, sender)})
        else:
            lines.append({'ok': False, 'text': 'No SMS account is set up, so '
                          'nothing can be sent.'})
        lines.append({'ok': False, 'text': 'A reply by SMS is kept in the '
                      'conversation, but it does not start a flow or move one on yet.'})
        return lines

    def receive(self, env, source_record):
        return {
            'wa_id': source_record.number,
            'body': source_record.body or '',
            'external_session_id': source_record.number,
            'source_model': 'sms.sms',
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return partner.mobile or partner.phone

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        return bool(partner.mobile or partner.phone)


adapter_registry.register_adapter('sms', SmsAdapter)
