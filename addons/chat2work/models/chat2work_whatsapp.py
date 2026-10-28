# -*- coding: utf-8 -*-
"""Chat2Work on WhatsApp: the USSD conversation with WhatsApp controls.

Same screens and rules as USSD (chat2work.flow), shown as reply buttons (up to
3 options) or a list (more), with a welcome image on the first screen. Typed
replies work too: the option number or its label.

Routing: a message containing a start keyword (chat2work.wa_triggers, default
"chat2work", so the flyer QR text "Hi Chat2Work FLYER" works) opens a session;
while a session is active, every message from that number comes here. Nothing
else reaches the generic chatbot engine, which would create a contact for the
sender before consent. Any words after the keyword are kept as the campaign
source tag (FLYER, CAR, ...).
"""

import logging
import re
from datetime import timedelta

from odoo import api, fields, models

from .chat2work_ussd import normalize_msisdn

_logger = logging.getLogger(__name__)

SESSION_MINUTES = 30
ID_PREFIX = 'c2w:'  # on button/list ids, so taps on an expired session's buttons are recognisably ours
BUTTON_TITLE_MAX = 20
ROW_TITLE_MAX = 24
BODY_MAX = 1024

# WhatsApp wording where the USSD text doesn't fit a chat.
WA_PROMPTS = {
    'S01B': ("Welcome to Chat2Work! 👋\n\n"
             "Join our workforce database and get help with a polished CV, free.\n\n"
             "What would you like to do?"),
    'S04': "Please type your 13-digit SA ID number.",
}


class Chat2workWaSession(models.Model):
    _name = 'chat2work.wa.session'
    _inherit = 'chat2work.flow'
    _description = 'Chat2Work WhatsApp Session'
    _order = 'write_date desc'
    _rec_name = 'wa_id'
    _channel = 'whatsapp'

    wa_id = fields.Char('WhatsApp ID', required=True, index=True, readonly=True)
    account_id = fields.Many2one('comm.whatsapp.account', readonly=True, ondelete='set null')
    source_tag = fields.Char(readonly=True)

    _sql_constraints = [
        ('wa_id_unique', 'UNIQUE(wa_id)', 'One Chat2Work WhatsApp session per number.'),
    ]

    # ── Channel specifics ────────────────────────────────────────────────────

    def _restart_phrase(self):
        return 'send "Hi Chat2Work"'

    def _after_consent(self):
        # They're messaging us on WhatsApp, so the USSD "do you use WhatsApp?"
        # question answers itself.
        self._set(whatsapp=True)
        return self._goto('S04')

    def _back_from_id(self):
        return self._goto('S02')

    def _candidate_extra_vals(self):
        return {'source_tag': self.source_tag or False}

    def _after_profile_created(self, candidate):
        # The CV link goes out in this conversation (see _send_turn).
        candidate._c2w_ensure_token()

    def _profile_created_text(self, candidate):
        return "Profile created! ✅ We'll contact you here on WhatsApp or by SMS."

    def _screen(self, screen):
        prompt, options = super()._screen(screen)
        return WA_PROMPTS.get(screen, prompt), options

    # ── Config ───────────────────────────────────────────────────────────────

    @api.model
    def _triggers(self):
        raw = self.env['ir.config_parameter'].sudo().get_param('chat2work.wa_triggers', 'chat2work')
        return [t.strip().lower() for t in raw.split(',') if t.strip()]

    @api.model
    def _match_trigger(self, text):
        """The source tag ('' if none) when `text` starts a session, else None."""
        low = (text or '').strip().lower()
        for trigger in self._triggers():
            idx = low.find(trigger)
            if idx != -1:
                tag = (text or '').strip()[idx + len(trigger):].strip(' -:')
                return re.sub(r'[^A-Za-z0-9_-]', '', tag)[:30].upper()
        return None

    @api.model
    def _account_allowed(self, account):
        only = self.env['ir.config_parameter'].sudo().get_param('chat2work.wa_phone_number_id')
        return not only or (account and account.phone_number_id == only)

    def _welcome_image_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('chat2work.wa_welcome_image_url')
        if not url:  # unset → the bundled image; set to "none" to send no image
            base = self.env['chat2work.candidate']._c2w_base_url()
            url = base + '/chat2work/static/src/img/wa_welcome.png' if base else ''
        return url if url and url != 'none' else ''

    # ── Inbound ──────────────────────────────────────────────────────────────

    @api.model
    def _reply_input(self, webhook_message):
        """(input, is_text) from a webhook message: a button/list id, or the typed text."""
        mtype = webhook_message.get('type')
        if mtype == 'interactive':
            inter = webhook_message.get('interactive') or {}
            reply = inter.get('button_reply') or inter.get('list_reply') or {}
            return (reply.get('id') or reply.get('title') or '').strip(), False
        if mtype == 'button':  # quick-reply on a template
            btn = webhook_message.get('button') or {}
            return (btn.get('payload') or btn.get('text') or '').strip(), False
        if mtype == 'text':
            return ((webhook_message.get('text') or {}).get('body') or '').strip(), True
        return '', True

    def _normalise_choice(self, inp):
        """Map a typed label ('yes', 'Create profile') to its option key."""
        if self.screen == 'S04':
            return re.sub(r'\s+', '', inp)
        _prompt, options = self._screen(self.screen)
        low = inp.strip().lower().rstrip('.')
        for key, label in options:
            if low in (key, label.lower()):
                return key
        return inp.strip()

    @api.model
    def wa_handle(self, webhook_message, value_data):
        """Handle one inbound WhatsApp message. Returns True if Chat2Work took it."""
        self = self.sudo()
        wa_id = re.sub(r'\D', '', webhook_message.get('from') or '')
        if not wa_id:
            return False
        phone_number_id = ((value_data or {}).get('metadata') or {}).get('phone_number_id')
        account = self.env['comm.whatsapp.account'].sudo().find_for_phone_number_id(phone_number_id)
        if not self._account_allowed(account):
            return False
        inp, is_text = self._reply_input(webhook_message)

        session = self.search([('wa_id', '=', wa_id)], limit=1)
        if session and session.write_date < fields.Datetime.now() - timedelta(minutes=SESSION_MINUTES):
            session.unlink()
            session = self.browse()
        tag = self._match_trigger(inp) if is_text else None
        ours = inp.startswith(ID_PREFIX)
        inp = inp[len(ID_PREFIX):] if ours else inp
        if not session and tag is None:
            if not ours:
                return False
            # A tap on a button from a session that has since expired.
            self.env['whatsapp.message'].send_whatsapp_payload(
                wa_id, {'type': 'text', 'text': {'body': 'Your session expired. Send "Hi Chat2Work" to start again.'}},
                account=account or None, log_body='Chat2Work session expired', log_type='text')
            return True
        try:
            if tag is not None:
                # A start keyword always starts over, even mid-session.
                session.unlink()
                session = self.create({
                    'wa_id': wa_id,
                    'msisdn': normalize_msisdn(wa_id),
                    'account_id': account.id or False,
                    'source_tag': tag or False,
                })
                body, end = session._start()
            else:
                body, end = session._advance(session._normalise_choice(inp))
            session._send_turn(body, end)
        except Exception:
            _logger.exception("chat2work WhatsApp error for %s", wa_id)
            self.env['whatsapp.message'].send_whatsapp_payload(
                wa_id, {'type': 'text', 'text': {'body': 'Service unavailable. Please try again later.'}},
                account=account or None, log_body='Service unavailable', log_type='text')
            session.exists().unlink()
        return True

    # ── Outbound ─────────────────────────────────────────────────────────────

    def _send(self, content, log_body, log_type='interactive'):
        res = self.env['whatsapp.message'].sudo().send_whatsapp_payload(
            self.wa_id, content, account=self.account_id or None, log_body=log_body, log_type=log_type)
        if not res.get('success'):
            _logger.warning("chat2work WhatsApp send to %s failed: %s", self.wa_id, res.get('error'))
        return res

    def _send_turn(self, body, end):
        self.ensure_one()
        if end:
            self._send({'type': 'text', 'text': {'body': body[:4096]}}, body, 'text')
            candidate = self.env['chat2work.candidate'].browse((self.data or {}).get('created_candidate_id')).exists()
            if candidate:
                self._send_cv_link(candidate)
            self.unlink()
            return
        prompt, options = self._screen(self.screen)
        if body.startswith("Invalid choice"):
            prompt = "Sorry, I didn't get that. Please choose an option below.\n\n" + prompt
        header_image = self.screen in ('S01A', 'S01B') and self._welcome_image_url()
        self._send(self._interactive(prompt, options, header_image), prompt)

    @api.model
    def _interactive(self, prompt, options, header_image=''):
        body = {'text': prompt[:BODY_MAX]}
        if len(options) <= 3:
            inter = {
                'type': 'button',
                'body': body,
                'action': {'buttons': [
                    {'type': 'reply', 'reply': {'id': ID_PREFIX + key, 'title': label[:BUTTON_TITLE_MAX]}}
                    for key, label in options
                ]},
            }
            if header_image:
                inter['header'] = {'type': 'image', 'image': {'link': header_image}}
        else:
            inter = {
                'type': 'list',
                'body': body,
                'action': {
                    'button': 'Choose',
                    'sections': [{'title': 'Options', 'rows': [
                        {'id': ID_PREFIX + key, 'title': label[:ROW_TITLE_MAX]} for key, label in options
                    ]}],
                },
            }
        return {'type': 'interactive', 'interactive': inter}

    def _send_cv_link(self, candidate):
        url = candidate._c2w_cv_url()
        content = {
            'type': 'interactive',
            'interactive': {
                'type': 'cta_url',
                'body': {'text': ("Next step: add your CV. Upload one you already have, or answer a few "
                                  "questions and we'll create a polished CV for you. You can also ask "
                                  "us to help.\n\nThe link is personal and works for 30 days.")},
                'footer': {'text': 'Chat2Work never asks for money.'},
                'action': {'name': 'cta_url', 'parameters': {'display_text': 'Add my CV', 'url': url}},
            },
        }
        res = self._send(content, 'CV link: %s' % url)
        candidate.sudo().write({
            # 'wa_sent' until Meta reports delivery; the cron falls back to SMS otherwise.
            'cv_link_state': 'wa_sent' if res.get('success') else 'queued',
            'cv_link_sent_at': fields.Datetime.now(),
            'cv_link_wa_message_id': res.get('message_id') or False,
        })
        if not res.get('success'):
            # Couldn't reach them in the chat: fall back to template/SMS.
            candidate._c2w_queue_cv_link()

    @api.model
    def _gc_stale_sessions(self):
        cutoff = fields.Datetime.now() - timedelta(minutes=SESSION_MINUTES)
        self.sudo().search([('write_date', '<', cutoff)]).unlink()


class WhatsAppChatbotMessageChat2work(models.Model):
    _inherit = 'whatsapp.chatbot.message'

    def process_incoming_webhook_message(self, wa_message, webhook_message, value_data, entry_data):
        if wa_message and wa_message.is_incoming:
            try:
                if self.env['chat2work.wa.session'].sudo().wa_handle(webhook_message, value_data):
                    return
            except Exception:
                _logger.exception("chat2work WhatsApp routing failed; passing to the chatbot engine")
        return super().process_incoming_webhook_message(wa_message, webhook_message, value_data, entry_data)
