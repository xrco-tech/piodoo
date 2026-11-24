# -*- coding: utf-8 -*-
"""One email exchange between a contact and a bot.

Odoo delivers a mail sent to an address (a mail.alias) to a record of the
model the address belongs to. An address connected to a bot belongs to this
model: the first mail makes a thread and starts the bot, and every reply in
the same email thread comes back to the same record and carries the bot on.
The bot's own replies are posted on the thread, so they go out as proper
replies in that email thread.
"""
import logging
import re

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# After this many mails from the other side a thread stops being answered:
# two auto-responders must not write to each other for ever.
MAX_INBOUND = 30

# Where the quoted earlier mail starts in a reply.
QUOTE = re.compile(
    r'^\s*(>|On .{0,200}wrote:|-{2,}\s*Original Message|From:\s|Sent from my )',
    re.IGNORECASE)


class CommBotEmailThread(models.Model):
    _name = 'comm.bot.email.thread'
    _description = 'Email exchange with a bot'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Subject', required=True)
    bot_id = fields.Many2one('comm.bot', string='Flow', ondelete='set null', index=True)
    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null', index=True)
    conversation_id = fields.Many2one('comm.conversation', ondelete='set null', index=True)
    email_from = fields.Char(string='From')
    inbound_count = fields.Integer(default=0)

    # ── What the other side wrote ────────────────────────────────────────

    @api.model
    def _reply_text(self, body):
        """The part of a mail the sender typed, without the earlier mail most
        mail programs quote underneath."""
        html = body or ''
        # A quoted block is the earlier mail, however the mail program marks it.
        html = re.sub(r'(?is)<blockquote.*?</blockquote>', '', html)
        # Many mail programs put each line in a block of its own.
        html = re.sub(r'(?i)</div\s*>', '</div><br/>', html)
        lines = []
        for line in html2plaintext(html).splitlines():
            if QUOTE.match(line):
                break
            lines.append(line)
        return '\n'.join(lines).strip()

    # ── The mail gateway ─────────────────────────────────────────────────

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        values = dict(custom_values or {})
        email_from = msg_dict.get('email_from') or ''
        partner = self.env['res.partner'].sudo().find_or_create(email_from) \
            if email_from else self.env['res.partner']
        values.update({
            'name': msg_dict.get('subject') or 'No subject',
            'email_from': email_from,
            'partner_id': partner.id,
        })
        thread = super().message_new(msg_dict, custom_values=values)
        thread._on_mail(msg_dict, first=True)
        return thread

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for thread in self:
            thread._on_mail(msg_dict, first=False)
        return res

    def _on_mail(self, msg_dict, first):
        """Start the bot on the first mail, hand it the answer on a reply.
        Never lets a failure stop the mail from being kept."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.sudo()._run_bot(msg_dict, first)
        except Exception:
            _logger.exception('comm_chatbot_email: bot did not run for thread %s', self.id)

    def _run_bot(self, msg_dict, first):
        self.inbound_count += 1
        bot = self.bot_id
        if msg_dict.get('is_bounce') or not self.partner_id or not bot:
            return
        if not bot.active or bot.engine_mode not in ('live', 'shadow'):
            return
        if self.inbound_count > MAX_INBOUND:
            _logger.warning('comm_chatbot_email: thread %s no longer answered after %s mails',
                            self.id, MAX_INBOUND)
            return
        channel = self.env['comm.channel'].get_by_code('email')
        if not channel:
            return
        Executor = self.env['comm.chatbot.executor']
        conversation = self.conversation_id
        if not conversation or conversation.lifecycle_state not in ('open', 'waiting'):
            if not first and conversation:
                # The flow already ended in this thread: a later reply does
                # not start it over.
                return
            conversation = self.env['comm.conversation'].find_or_open(
                self.partner_id, bot, channel, self.email_from)
            self.conversation_id = conversation
        leg = Executor._ensure_leg(conversation, channel, self._name, self.id, self.email_from)
        conversation.primary_channel_id = channel
        # The mail itself is put on the conversation when it is stored (the
        # inbox does that for every email), so it is not logged again here.
        conversation.touch()
        step = conversation.current_step_id
        if not first and step and step.kind in ('menu', 'input'):
            Executor._handle_input(conversation, leg, self._reply_text(msg_dict.get('body')))
        else:
            Executor.advance(conversation, leg)

    # ── What the bot writes back ─────────────────────────────────────────

    def _send_reply(self, body_html, email_from, subject=None):
        """Post the bot's message on the thread, to the contact: it goes out as
        a reply in the same email thread, and answers come back here."""
        self.ensure_one()
        return self.sudo().message_post(
            body=body_html,
            subject=subject or ('Re: %s' % self.name),
            partner_ids=self.partner_id.ids,
            email_from=email_from or None,
            reply_to=email_from or None,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
