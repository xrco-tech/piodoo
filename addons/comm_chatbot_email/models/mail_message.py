# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        try:
            messages._thread_email_to_comm()
        except Exception:  # threading must never block mail delivery
            _logger.exception('comm_chatbot_email: threading email to comm.interaction failed')
        return messages

    def _thread_email_to_comm(self):
        """Surface real emails in the omnichannel inbox: create a comm.interaction
        on the 'email' channel for each genuine email (message_type='email'),
        threaded to a conversation for the partner. Gated by
        comm_chatbot_email.thread_to_inbox (default on)."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('comm_chatbot_email.thread_to_inbox', '1') in ('0', 'False', 'false'):
            return
        channel = self.env.ref('comm_chatbot_email.channel_email', raise_if_not_found=False)
        if not channel:
            return
        Conv = self.env['comm.conversation']
        Interaction = self.env['comm.interaction']
        for msg in self:
            if msg.message_type != 'email' or not msg.author_id:
                continue
            if Interaction.search_count([
                    ('source_model', '=', 'mail.message'), ('source_id', '=', msg.id)]):
                continue  # already threaded
            author = msg.author_id
            if author.user_ids:  # sent by an internal user → outbound
                direction = 'outbound'
                recipients = msg.partner_ids.filtered(lambda p: not p.user_ids)
                partner = recipients[:1] or msg.partner_ids[:1]
            else:                # external sender → inbound
                direction = 'inbound'
                partner = author
            if not partner:
                continue
            conv = Conv.search([
                ('partner_id', '=', partner.id),
                ('lifecycle_state', 'in', ('open', 'waiting')),
            ], limit=1, order='last_activity_at desc') or Conv.create({
                'partner_id': partner.id,
                'primary_channel_id': channel.id,
            })
            subject = msg.subject or ''
            text = html2plaintext(msg.body) if msg.body else ''
            body = ('%s\n\n%s' % (subject, text)).strip() if subject else text
            Interaction.create({
                'conversation_id': conv.id,
                'channel_id': channel.id,
                'direction': direction,
                'at': msg.date or fields.Datetime.now(),
                'raw_body': body,
                'rendered_body': body,
                'status': 'received' if direction == 'inbound' else 'sent',
                'source_model': 'mail.message',
                'source_id': msg.id,
            })
            conv.touch()
