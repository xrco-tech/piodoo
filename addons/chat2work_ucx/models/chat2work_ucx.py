# -*- coding: utf-8 -*-
"""Chat2Work activity on the candidate's UCX conversation.

Each candidate's contact gets one open comm.conversation (an open one is
reused, so Chat2Work entries sit in the same thread as the person's other
messages), and Chat2Work's log hooks become comm.interaction rows on it.
"""

import logging

from odoo import fields, models

from odoo.addons.chat2work.models.chat2work_ussd import msisdn_variants

_logger = logging.getLogger(__name__)

DEFAULT_STATUS = {'inbound': 'received', 'outbound': 'sent'}
# Meta's statuses, in the order they happen; a late webhook never moves one back.
WA_STATUS_RANK = {'sent': 1, 'delivered': 2, 'read': 3, 'failed': 4}
OPEN_STATES = ('open', 'waiting', 'handoff')


class Chat2workCandidateUcx(models.Model):
    _inherit = 'chat2work.candidate'

    def _c2w_ucx_partner(self):
        """The candidate's contact, created now if they don't have one (they've
        consented by the time they're a candidate)."""
        self.ensure_one()
        rec = self.sudo()
        if rec.partner_id:
            return rec.partner_id
        Partner = self.env['res.partner'].sudo()
        partner = Partner.browse()
        if rec.phone:
            variants = msisdn_variants(rec.phone)
            partner = Partner.search(['|', ('mobile', 'in', variants), ('phone', 'in', variants)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': rec.name or 'Chat2Work %s' % rec._c2w_display_phone(),
                'mobile': rec.phone or False,
            })
        rec.partner_id = partner
        return partner

    def _c2w_ucx_conversation(self, channel):
        partner = self._c2w_ucx_partner()
        Conversation = self.env['comm.conversation'].sudo()
        conversation = Conversation.search([
            ('partner_id', '=', partner.id), ('lifecycle_state', 'in', OPEN_STATES),
        ], order='last_activity_at desc', limit=1)
        if conversation:
            conversation.touch()
            return conversation
        return Conversation.create({
            'partner_id': partner.id,
            'primary_channel_id': channel.id,
            'campaign_id': 'chat2work',
        })

    def _c2w_ucx_log(self, channel_code, entries):
        """Write [{'dir', 'text', 'at'?, 'status'?, 'wa'?}] to the candidate's
        conversation. Never raises: the log must not break the flow."""
        self.ensure_one()
        if not entries:
            return
        try:
            with self.env.cr.savepoint():
                channel = self.env['comm.channel'].sudo().search([('code', '=', channel_code)], limit=1)
                if not channel:
                    _logger.warning("chat2work_ucx: no comm.channel %r; not logged", channel_code)
                    return
                conversation = self._c2w_ucx_conversation(channel)
                WaMessage = self.env['whatsapp.message'].sudo()
                vals_list = []
                for entry in entries:
                    source = WaMessage.search([('message_id', '=', entry['wa'])], limit=1) \
                        if entry.get('wa') else WaMessage
                    vals_list.append({
                        'conversation_id': conversation.id,
                        'channel_id': channel.id,
                        'direction': entry['dir'],
                        'at': entry.get('at') or fields.Datetime.now(),
                        'raw_body': entry['text'],
                        'rendered_body': entry['text'],
                        'status': entry.get('status') or DEFAULT_STATUS[entry['dir']],
                        'source_model': source._name if source else False,
                        'source_id': source.id or False,
                    })
                self.env['comm.interaction'].sudo().create(vals_list)
        except Exception:
            _logger.exception("chat2work_ucx: couldn't log %s activity for candidate %s", channel_code, self.id)

    def _c2w_log_session(self, channel, transcript):
        super()._c2w_log_session(channel, transcript)
        self.ensure_one()
        if channel != 'ussd':
            self._c2w_ucx_log(channel, transcript)
            return
        # USSD screens are short-lived menus: one entry per session reads better.
        choices = [e['text'] for e in transcript if e['dir'] == 'inbound']
        result = next((e['text'] for e in reversed(transcript) if e['dir'] == 'outbound'), '')
        body = 'USSD session: %s\nResult: %s' % (' › '.join(choices) or 'no choices made', result)
        self._c2w_ucx_log('ussd', [{'dir': 'inbound', 'text': body, 'at': transcript[0].get('at')}])

    def _c2w_log_event(self, channel, direction, body, status=None, wa_message_id=None):
        super()._c2w_log_event(channel, direction, body, status, wa_message_id)
        for rec in self:
            rec._c2w_ucx_log(channel, [{'dir': direction, 'text': body, 'status': status, 'wa': wa_message_id}])


class WhatsAppMessageUcxStatus(models.Model):
    """Keep Chat2Work's WhatsApp entries on the timeline at Meta's latest status."""
    _inherit = 'whatsapp.message'

    def write(self, vals):
        res = super().write(vals)
        status = vals.get('message_status')
        if status in WA_STATUS_RANK and self.ids:
            interactions = self.env['comm.interaction'].sudo().search([
                ('source_model', '=', 'whatsapp.message'), ('source_id', 'in', self.ids),
            ])
            interactions.filtered(
                lambda i: WA_STATUS_RANK.get(i.status, 0) < WA_STATUS_RANK[status]
            ).write({'status': status})
        return res
