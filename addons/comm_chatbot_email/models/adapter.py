# -*- coding: utf-8 -*-
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


class EmailAdapter:
    """Email channel adapter for comm_chatbot.

    Follows the comm_chatbot_sms.SmsAdapter shape exactly (send / receive /
    open_session / close_session / can_reach) so the engine treats email like
    any other channel. Outbound goes through mail.mail; inbound is fed a
    mail.message / mail.mail source record by the mail-gateway wiring.
    """
    channel_code = 'email'

    def send(self, env, interaction, payload):
        conversation = interaction.conversation_id
        email = conversation.partner_id.email
        if not email:
            return {'status': 'failed', 'error': 'no email on partner'}

        Mail = env['mail.mail'].sudo()
        body = payload.get('body', '')
        try:
            mail = Mail.create({
                'email_to': email,
                'subject': payload.get('subject') or (conversation.name or 'Message'),
                'body_html': body,
                'author_id': env.user.partner_id.id,
            })
            mail.send()
        except Exception as e:
            _logger.warning('Email send failed: %s', e)
            return {'status': 'failed', 'error': str(e)}

        return {'status': 'sent', 'source_model': 'mail.mail',
                'source_id': mail.id}

    def receive(self, env, source_record):
        # source_record is a mail.message or mail.mail carrying the inbound email.
        sender = getattr(source_record, 'email_from', False) or ''
        return {
            'wa_id': sender,
            'body': source_record.body or '',
            'external_session_id': sender,
            'source_model': source_record._name,
            'source_id': source_record.id,
        }

    def open_session(self, env, conversation, partner):
        return partner.email

    def close_session(self, env, leg):
        return None

    def can_reach(self, env, partner):
        return bool(partner.email)


adapter_registry.register_adapter('email', EmailAdapter)
