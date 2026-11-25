# -*- coding: utf-8 -*-
"""Every inbound SMS goes into the sender's UCX conversation, so replies to
our SMS are never lost. An SMS that is a flow's keyword starts that flow, and
an SMS from someone a flow is waiting on is their answer."""

import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OPEN_STATES = ('open', 'waiting', 'handoff')


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    @api.model
    def _comm_record_inbound(self, partner, number, body, provider_message_id=None, to_number=None):
        super()._comm_record_inbound(partner, number, body, provider_message_id, to_number)
        if not partner:
            return False
        channel = self.env.ref('comm_chatbot.channel_sms', raise_if_not_found=False)
        if not channel:
            return False
        Conversation = self.env['comm.conversation'].sudo()
        conversation = Conversation.search([
            ('partner_id', '=', partner.id), ('lifecycle_state', 'in', OPEN_STATES),
        ], order='last_activity_at desc', limit=1)

        # A flow first. If it fails, the SMS is still kept below.
        try:
            with self.env.cr.savepoint():
                interaction = self._comm_flow_inbound(
                    channel, partner, conversation, number, body, to_number)
            if interaction:
                return interaction
        except Exception:
            _logger.exception("A flow could not take the inbound SMS from partner %s", partner.id)

        conversation = conversation or Conversation.create({
            'partner_id': partner.id,
            'primary_channel_id': channel.id,
        })
        interaction = self.env['comm.interaction'].sudo().create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'direction': 'inbound',
            'at': fields.Datetime.now(),
            'raw_body': body or '',
            'rendered_body': body or '',
            'status': 'received',
        })
        conversation.touch()
        return interaction

    # ------------------------------------------------------------------
    # Flows
    # ------------------------------------------------------------------
    @api.model
    def _comm_inbound_account(self, to_number):
        """The SMS account an inbound SMS was sent to: the one whose sender is
        `to_number`, however the number is written. The default account when
        the provider does not say where the SMS was sent."""
        Account = self.env['comm.sms.account'].sudo()
        to_number = (to_number or '').strip()
        if not to_number:
            return Account.get_default()
        account = Account.find_for_sender_id(to_number) or Account.search(
            [('sender_id', '=ilike', to_number)], limit=1)
        digits = re.sub(r'\D', '', to_number)
        if not account and digits:
            account = Account.search([]).filtered(
                lambda a: re.sub(r'\D', '', a.sender_id or '') == digits)[:1]
        return account

    @api.model
    def _comm_flow_inbound(self, channel, partner, conversation, number, body, to_number):
        """Give the SMS to a flow, when one should have it. Returns the
        interaction the flow logged, or nothing.

        - Someone a flow on SMS is in the middle of: the SMS is their answer.
        - Otherwise, the SMS is the keyword of a flow connected to the sender
          it came in on: that flow starts.
        - A conversation handed to a person is left to that person.
        """
        if conversation.lifecycle_state == 'handoff':
            return False
        Executor = self.env['comm.chatbot.executor'].sudo()
        bot = conversation.bot_id
        target = False
        if bot and conversation.current_step_id and channel in bot.channel_ids:
            target = conversation
        else:
            account = self._comm_inbound_account(to_number)
            trigger = self.env['comm.bot.trigger'].sudo().with_context(
                comm_trigger_domain=[('bot_id.sms_account_id', '=', account.id or 0)],
            ).find_trigger('sms', body or '')
            if not trigger or not trigger.bot_id.entry_step_id:
                return False
            if conversation and not bot:
                # The conversation their earlier SMS opened: the flow joins it.
                conversation.write({
                    'bot_id': trigger.bot_id.id,
                    'current_step_id': trigger.bot_id.entry_step_id.id,
                })
                target = conversation
            else:
                # Nothing open, or a flow on another channel is: a new one.
                target = self.env['comm.conversation'].sudo().create({
                    'partner_id': partner.id,
                    'bot_id': trigger.bot_id.id,
                    'primary_channel_id': channel.id,
                    'current_step_id': trigger.bot_id.entry_step_id.id,
                })
        return Executor.on_inbound(
            channel_code='sms', source_model=False, source_id=False,
            wa_id=number, body=body or '', external_session_id=number,
            partner=partner, conversation=target) or False
