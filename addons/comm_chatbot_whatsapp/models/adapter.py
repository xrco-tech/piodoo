# -*- coding: utf-8 -*-
"""WhatsApp channel adapter.

Registers with comm_chatbot's adapter registry at module load. Adapter is a
plain Python class (not an Odoo model) — the registry maps 'whatsapp' →
WhatsappAdapter.
"""
import logging
from odoo.addons.comm_chatbot.models.runtime import adapter_registry

_logger = logging.getLogger(__name__)


# Meta's limits for the parts of a message, in characters.
HEADER_MAX = 60
FOOTER_MAX = 60
BODY_MAX = 1024
BUTTON_MAX = 20
ROW_MAX = 24
ROW_ID_MAX = 200
CAPTION_MAX = 1024


def _framed(payload):
    """Header, body and footer as one text, for a message that has no place
    of its own for a header or a footer: bold first line, italic last."""
    parts = []
    if payload.get('header'):
        parts.append('*%s*' % payload['header'])
    if payload.get('body'):
        parts.append(payload['body'])
    if payload.get('footer'):
        parts.append('_%s_' % payload['footer'])
    return '\n\n'.join(parts)


def build_content(payload):
    """What to send to WhatsApp for one rendered step, as the Cloud API's
    type-specific content, or None for a plain text message.

    - Choices: reply buttons (three at most) or a list, with the step's
      header (its image, else its header line), body and footer.
    - An image and no choices: the image, with the text as its caption.
    - Neither: None; the caller sends the text.

    Choices the renderer already numbered into the body are sent as text.
    """
    options = [o for o in payload.get('options') or [] if not o.get('numeric_key')]
    image = next((m for m in payload.get('media') or []
                  if m.get('kind') == 'image' and m.get('url')), None)
    if not options:
        if image:
            return {'type': 'image', 'image': {
                'link': image['url'], 'caption': _framed(payload)[:CAPTION_MAX]}}
        return None

    interactive = {
        # WhatsApp refuses an interactive message with an empty body.
        'body': {'text': (payload.get('body') or payload.get('header')
                          or '-')[:BODY_MAX]},
    }
    if image:
        interactive['header'] = {'type': 'image', 'image': {'link': image['url']}}
    elif payload.get('header') and payload.get('body'):
        interactive['header'] = {'type': 'text', 'text': payload['header'][:HEADER_MAX]}
    if payload.get('footer'):
        interactive['footer'] = {'text': payload['footer'][:FOOTER_MAX]}
    if len(options) <= 3:
        interactive['type'] = 'button'
        interactive['action'] = {'buttons': [{
            'type': 'reply',
            'reply': {'id': (o.get('value') or o['label'])[:ROW_ID_MAX],
                      'title': o['label'][:BUTTON_MAX]},
        } for o in options]}
    else:
        interactive['type'] = 'list'
        interactive['action'] = {
            'button': 'Choose',
            'sections': [{'rows': [{
                'id': (o.get('value') or o['label'])[:ROW_ID_MAX],
                'title': o['label'][:ROW_MAX],
            } for o in options[:10]]}],
        }
    return {'type': 'interactive', 'interactive': interactive}


class WhatsappAdapter:
    channel_code = 'whatsapp'

    def send(self, env, interaction, payload):
        """Send an outbound bot message through the WhatsApp account.

        payload = {'header', 'body', 'footer', 'options', 'media', ...}
        Returns dict with status + source_model + source_id.
        """
        conversation = interaction.conversation_id
        wa_id = conversation.partner_id.whatsapp_id or conversation.partner_id.mobile
        if not wa_id:
            return {'status': 'failed', 'error': 'no wa_id on partner'}
        account = env['comm.whatsapp.account'].sudo().get_default()
        if not account:
            return {'status': 'failed', 'error': 'no active WhatsApp account'}

        Message = env['whatsapp.message'].sudo()
        content = build_content(payload)
        text = _framed(payload)
        if content:
            result = Message.send_whatsapp_payload(
                wa_id, content, account=account, log_body=text,
                log_type=content['type'])
        else:
            result = Message.send_whatsapp_message(wa_id, text, account=account)
        result = result or {}
        if not result.get('success'):
            return {'status': 'failed',
                    'error': result.get('error') or 'WhatsApp did not accept the message'}
        return {'status': 'sent', 'source_model': 'whatsapp.message',
                'source_id': False}

    def connections(self, env, bot):
        """The WhatsApp number this bot sends from, and what starts it."""
        lines = []
        account = env['comm.whatsapp.account'].sudo().get_default()
        if account:
            number = account.phone_number or 'no number on the account'
            lines.append({'ok': True, 'text': 'Sends from %s (%s). Every flow '
                          'uses the default WhatsApp account.' % (account.name, number)})
        else:
            lines.append({'ok': False, 'text': 'No WhatsApp account is set up, '
                          'so nothing can be sent.'})
        words = [t.value for t in bot.trigger_ids
                 if t.active and t.channel_id.code == 'whatsapp'
                 and t.kind == 'keyword' and t.value]
        if any(t.active and t.channel_id.code == 'whatsapp' and t.kind == 'any_inbound'
               for t in bot.trigger_ids):
            lines.append({'ok': True, 'text': 'Starts on any message that no '
                          'other flow picks up.'})
        elif words:
            lines.append({'ok': True, 'text': 'Starts when someone sends: %s.'
                          % ', '.join(words)})
        else:
            lines.append({'ok': False, 'text': 'No keyword starts this flow, so '
                          'a message from a contact will not reach it.'})
        return lines

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
