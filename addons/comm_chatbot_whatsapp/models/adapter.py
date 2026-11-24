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
        # The bot's own number; a conversation with no bot, or a bot that was
        # taken off its number mid-conversation, still goes out on the default.
        account = conversation.bot_id.sudo().whatsapp_account_id \
            or env['comm.whatsapp.account'].sudo().get_default()
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

    # Flows on this channel are started by a keyword someone sends.
    keyword_start = True
    connect_noun = 'number'

    def connections(self, env, bot):
        """The WhatsApp number this bot answers on, and whether anything
        starts it."""
        lines = []
        account = bot.sudo().whatsapp_account_id
        if account:
            number = account.phone_number or 'no number on the account'
            lines.append({'ok': True, 'text': 'Answers on and sends from %s (%s).'
                          % (account.name, number),
                          'name': account.name, 'address': account.phone_number or '',
                          'model': account._name, 'res_id': account.id,
                          'option_id': account.id})
        elif env['comm.whatsapp.account'].sudo().search_count([]):
            lines.append({'ok': False, 'text': 'No WhatsApp number is connected '
                          'to this flow, so no message starts it.'})
        else:
            lines.append({'ok': False, 'text': 'No WhatsApp account is set up, '
                          'so nothing can be sent.'})
        starts = [t for t in bot.trigger_ids
                  if t.active and t.channel_id.code == 'whatsapp'
                  and (t.kind == 'any_inbound' or (t.kind == 'keyword' and t.value))]
        if account and not starts:
            lines.append({'ok': False, 'text': 'No keyword starts this flow, so '
                          'a message from a contact will not reach it.'})
        return lines

    def connect_options(self, env, bot):
        """The WhatsApp numbers this bot could answer on."""
        return [{
            'id': a.id,
            'label': '%s  %s' % (a.phone_number or '(no number)', a.name),
            'name': a.name,
            'code': a.phone_number or '',
            'runs': '',
            'ask_on': 'A message that comes in on %s and matches one of this '
                      'flow\'s keywords will start it, once the flow is live or '
                      'test only. The flow also sends from this number.'
                      % (a.phone_number or a.name),
            'ask_off': 'No message will start this flow on %s any more. '
                       'Conversations already under way carry on.'
                       % (a.phone_number or a.name),
            'connected': a == bot.sudo().whatsapp_account_id,
        } for a in env['comm.whatsapp.account'].sudo().search([])]

    def connect(self, env, bot, option_id, on):
        account = env['comm.whatsapp.account'].sudo().browse(option_id).exists()
        if not account:
            return
        if on:
            bot.sudo().whatsapp_account_id = account
        elif bot.sudo().whatsapp_account_id == account:
            bot.sudo().whatsapp_account_id = False

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
