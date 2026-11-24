# -*- coding: utf-8 -*-
import logging
import re

from markupsafe import Markup, escape

from odoo.exceptions import UserError
from odoo.tools import email_normalize, formataddr

from odoo.addons.comm_chatbot.models.runtime import adapter_registry

THREAD = 'comm.bot.email.thread'
# The part of an address before the @: letters, digits, dots, dashes, underscores.
LOCAL_PART = re.compile(r'^[a-z0-9][a-z0-9._-]{0,62}$')


def _as_html(text):
    """A step's text as the body of a mail: its line breaks kept."""
    return Markup('<br/>').join(escape(line) for line in (text or '').splitlines())

_logger = logging.getLogger(__name__)


class EmailAdapter:
    """Email channel adapter for comm_chatbot.

    Follows the comm_chatbot_sms.SmsAdapter shape exactly (send / receive /
    open_session / close_session / can_reach) so the engine treats email like
    any other channel. Outbound goes through mail.mail; inbound is fed a
    mail.message / mail.mail source record by the mail-gateway wiring.
    """
    channel_code = 'email'

    connect_noun = 'address'

    # ── Sending ──────────────────────────────────────────────────────────

    def _from(self, env, bot):
        """The address a bot's mail goes out from, with the company's name."""
        address = bot.sudo().email_alias_id.alias_full_name
        if not address or '@' not in address:
            return False
        return formataddr((env.company.name, address))

    def _text(self, payload):
        """Header, body, the choices as a numbered list, footer."""
        parts = [payload.get('header') or '', payload.get('body') or '']
        options = payload.get('options') or []
        if options:
            parts.append('\n'.join('%s. %s' % (i + 1, o.get('label') or '')
                                   for i, o in enumerate(options)))
        parts.append(payload.get('footer') or '')
        return '\n\n'.join(p for p in parts if p)

    def send(self, env, interaction, payload):
        conversation = interaction.conversation_id
        email = conversation.partner_id.email
        if not email:
            return {'status': 'failed', 'error': 'no email on partner'}
        body = _as_html(self._text(payload))
        email_from = self._from(env, conversation.bot_id)
        thread = env[THREAD].sudo().search(
            [('conversation_id', '=', conversation.id)], limit=1)
        try:
            if thread:
                # A reply in the email thread the contact wrote in.
                message = thread._send_reply(body, email_from, payload.get('subject'))
                return {'status': 'sent', 'source_model': 'mail.message',
                        'source_id': message.id}
            values = {
                'email_to': email,
                'subject': payload.get('subject') or (conversation.name or 'Message'),
                'body_html': body,
                'author_id': env.user.partner_id.id,
            }
            if email_from:
                values.update(email_from=email_from, reply_to=email_from)
            mail = env['mail.mail'].sudo().create(values)
            mail.send()
        except Exception as e:
            _logger.warning('Email send failed: %s', e)
            return {'status': 'failed', 'error': str(e)}

        return {'status': 'sent', 'source_model': 'mail.mail',
                'source_id': mail.id}

    # ── What a flow is connected to ──────────────────────────────────────

    def _thread_model(self, env):
        return env['ir.model'].sudo()._get(THREAD)

    def _domain(self, env):
        """The email domain new addresses are made on."""
        Domain = env['mail.alias.domain'].sudo()
        return env.company.sudo().alias_domain_id or Domain.search([], limit=1)

    def _owned(self, env):
        """The addresses made for flows."""
        return env['mail.alias'].sudo().search([
            ('alias_model_id', '=', self._thread_model(env).id),
            ('alias_name', '!=', False)])

    def _bot_of(self, env, alias):
        return env['comm.bot'].sudo().with_context(active_test=False).search(
            [('email_alias_id', '=', alias.id)], limit=1)

    def connections(self, env, bot):
        """The address that starts this bot, and whether mail can come in
        and go out for it."""
        lines = []
        alias = bot.sudo().email_alias_id
        if alias:
            address = alias.alias_full_name or alias.alias_name
            lines.append({'ok': True, 'text': 'Mail to %s starts this flow. Replies '
                          'go out from it.' % address,
                          'name': address,
                          'address': 'Mail to this address starts the flow. Replies go out from it.',
                          'model': alias._name, 'res_id': alias.id,
                          'option_id': alias.id})
            if '@' not in (address or ''):
                lines.append({'ok': False, 'text': 'This address has no email '
                              'domain, so no mail can reach it.',
                              'open_model': 'mail.alias.domain',
                              'open_label': 'Set up an email domain'})
            lines += self._server_lines(env, address)
        elif not self._domain(env):
            lines.append({'ok': False, 'text': 'Odoo has no email domain yet, so '
                          'there are no addresses to connect.',
                          'open_model': 'mail.alias.domain',
                          'open_label': 'Set up an email domain'})
        else:
            lines.append({'ok': False, 'text': 'No address is connected to this '
                          'flow, so no email starts it.'})
        return lines

    def _server_lines(self, env, address):
        """Which server brings the address's mail in, and which sends for it.
        Odoo works both out by itself; they are shown, not chosen."""
        lines = []
        incoming = env['fetchmail.server'].sudo().search([('state', '=', 'done')])
        if incoming:
            for server in incoming[:2]:
                lines.append({'ok': True, 'text': 'Mail comes in through %s.' % server.name,
                              'label': 'Comes in through', 'name': server.name,
                              'model': server._name, 'res_id': server.id})
        else:
            lines.append({'ok': False, 'text': 'No incoming mail server is fetching '
                          'mail, so a mail to this address may never arrive.',
                          'open_model': 'fetchmail.server',
                          'open_label': 'Set up incoming mail'})
        outgoing = env['ir.mail_server'].sudo()._find_mail_server(address or '')[0] \
            if email_normalize(address or '') else env['ir.mail_server']
        if outgoing:
            lines.append({'ok': True, 'text': 'Mail is sent by %s.' % outgoing.name,
                          'label': 'Sent by', 'name': outgoing.name,
                          'model': outgoing._name, 'res_id': outgoing.id})
        else:
            lines.append({'ok': False, 'text': 'No outgoing mail server can send '
                          'from this address, so the flow cannot reply.',
                          'open_model': 'ir.mail_server',
                          'open_label': 'Set up outgoing mail'})
        return lines

    def connect_options(self, env, bot):
        """Every address Odoo has. The ones made for flows can be chosen; the
        others are listed with what uses them, so none is taken by accident."""
        mine = bot.sudo().email_alias_id
        options = []
        for alias in self._owned(env):
            other = self._bot_of(env, alias)
            address = alias.alias_full_name or alias.alias_name
            options.append({
                'id': alias.id, 'label': address, 'name': address, 'code': '',
                'runs': other.name if other and other != bot else '',
                'ask_on': 'Mail sent to %s will start this flow, once the flow is '
                          'live or test only. The flow replies from the same '
                          'address.%s' % (address, (
                              ' It stops starting “%s”.' % other.name)
                              if other and other != bot else ''),
                'ask_off': 'Mail sent to %s will no longer start this flow. The '
                           'address is kept and can be connected again.' % address,
                'connected': alias == mine,
            })
        thread_model = self._thread_model(env)
        for alias in env['mail.alias'].sudo().search([
                ('alias_model_id', '!=', thread_model.id), ('alias_name', '!=', False)]):
            address = alias.alias_full_name or alias.alias_name
            options.append({
                'id': alias.id, 'label': address, 'name': address, 'code': '',
                'runs': '', 'note': 'used by %s' % alias.alias_model_id.name,
                'disabled': True, 'connected': False,
            })
        return options

    def connect(self, env, bot, option_id, on):
        alias = env['mail.alias'].sudo().browse(option_id).exists()
        if not alias:
            return
        if alias.alias_model_id != self._thread_model(env):
            raise UserError('%s is used by %s. Make a new address for this flow.'
                            % (alias.alias_full_name or alias.alias_name,
                               alias.alias_model_id.name))
        bot = bot.sudo()
        if on:
            self._bot_of(env, alias).write({'email_alias_id': False})
            self._release(bot.email_alias_id)
            alias.alias_defaults = repr({'bot_id': bot.id})
            bot.email_alias_id = alias
        elif bot.email_alias_id == alias:
            bot.email_alias_id = False
            self._release(alias)

    def _release(self, alias):
        """An address no flow is on keeps its mail but starts nothing."""
        if alias:
            alias.alias_defaults = '{}'

    def connect_new_hint(self, env, bot):
        """What follows the @ in a new address, for the screen to show."""
        domain = self._domain(env)
        return domain.name if domain else ''

    def connect_new(self, env, bot, name):
        """Make a new address on the email domain and connect the flow to it."""
        domain = self._domain(env)
        if not domain:
            raise UserError('Odoo has no email domain yet. Set one up first.')
        local = (name or '').strip().lower().split('@')[0]
        if not LOCAL_PART.match(local):
            raise UserError('Type the part before the @: letters, digits, dots, '
                            'dashes or underscores, for example jobs.')
        alias = env['mail.alias'].sudo().create({
            'alias_name': local,
            'alias_domain_id': domain.id,
            'alias_model_id': self._thread_model(env).id,
            'alias_contact': 'everyone',
            'alias_defaults': '{}',
        })
        self.connect(env, bot, alias.id, True)
        return alias.id

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
