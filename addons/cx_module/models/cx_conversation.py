# -*- coding: utf-8 -*-
"""UCX-level glue on the reused Gen-2 conversation models.

Per the reuse decision, UCX does not re-model conversations. This module only
adds the thin glue the unified inbox needs on top of comm.conversation /
comm.interaction:

- convenience related fields (channel *code*, not the m2o display name) so the
  OWL inbox can filter/badge by channel in a single search_read;
- an agent-reply entry point that mirrors the engine's own outbound path
  (comm_chatbot ...runtime/executor._send_body_only);
- a bus notification on every new interaction so the inbox updates live
  without a refresh (Phase 2 acceptance).
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Channels an agent can actually type a reply on from the inbox composer.
CX_SENDABLE_CHANNELS = ('whatsapp', 'sms', 'email')

# Fixed bus channel every open inbox subscribes to.
CX_INBOX_BUS_CHANNEL = 'cx_inbox'


class CommConversation(models.Model):
    _inherit = 'comm.conversation'

    primary_channel_code = fields.Char(
        related='primary_channel_id.code', string='Primary Channel Code')

    # Conversation wrap-up code — same shared taxonomy as call dispositions
    # (comm.disposition, defined in comm_whatsapp_calling). One outcome
    # scheme across voice and chat.
    disposition_id = fields.Many2one(
        'comm.disposition', string='Disposition', ondelete='set null', index=True,
        help='Outcome / wrap-up code the agent set for this conversation.')
    disposition_note = fields.Text('Disposition Note')

    def action_set_disposition(self, disposition_id, note=None):
        """Set (or clear) the disposition on this conversation. Callable
        from the inbox via ORM."""
        self.ensure_one()
        vals = {'disposition_id': disposition_id or False}
        if note is not None:
            vals['disposition_note'] = note
        self.write(vals)
        return True

    # ── Send template (from the inbox) ──────────────────────────────────
    # Reuses the shared contact.centre.template taxonomy so UCX and the CC
    # inbox pick from the same templates. Address is the conversation's
    # partner's email / mobile-or-phone.
    partner_email = fields.Char(related='partner_id.email', string='Contact Email')
    partner_mobile = fields.Char(related='partner_id.mobile', string='Contact Mobile')
    partner_phone = fields.Char(related='partner_id.phone', string='Contact Phone')

    def _template_address_error(self, channel):
        """Reason this conversation's contact can't receive a template on
        `channel` (missing address), or '' when it can."""
        self.ensure_one()
        p = self.partner_id
        if channel == 'email' and not (p and p.email):
            return "This contact has no email address set, so an email template cannot be sent."
        if channel in ('sms', 'whatsapp') and not (p and (p.mobile or p.phone)):
            label = 'SMS' if channel == 'sms' else 'WhatsApp'
            addr = 'phone number' if channel == 'sms' else 'WhatsApp number'
            return "This contact has no %s set, so a %s template cannot be sent." % (addr, label)
        return ""

    def action_send_template(self, template_id):
        """Send a contact.centre.template on its channel to this
        conversation's contact. Validates the address first (returns
        {'error': msg}); else sends via the engine's own outbound path
        (action_cx_send_reply) and returns {'success': True}."""
        self.ensure_one()
        template = self.env['contact.centre.template'].browse(int(template_id))
        if not template.exists():
            return {'error': "Template not found."}
        err = self._template_address_error(template.channel)
        if err:
            return {'error': err}
        self.action_cx_send_reply(template.channel, template.body_text or "")
        return {'success': True}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            self.env['cx.integration.webhook']._cx_enqueue_event(
                'conversation.opened', {
                    'event': 'conversation.opened',
                    'conversation_id': rec.id,
                    'partner_id': rec.partner_id.id,
                    'channel': rec.primary_channel_id.code or None,
                })
        return records

    def action_cx_send_reply(self, channel_code, text):
        """Send an agent-typed reply on the given channel.

        Mirrors the engine's outbound path: create an outbound comm.interaction,
        resolve the channel adapter, and hand it the body to push to the
        provider. Returns the new interaction id (or False for empty input).
        """
        self.ensure_one()
        text = (text or '').strip()
        if not text:
            return False

        channel = self.env['comm.channel'].sudo().search(
            [('code', '=', channel_code)], limit=1) or self.primary_channel_id
        if not channel:
            _logger.warning('cx reply: no channel for code %r on conversation %s',
                            channel_code, self.id)
            return False

        interaction = self.env['comm.interaction'].create({
            'conversation_id': self.id,
            'channel_id': channel.id,
            'direction': 'outbound',
            'raw_body': text,
            'rendered_body': text,
            'status': 'rendered',
        })

        adapter = self.env['comm.chatbot.registry'].get_adapter_for_channel(channel)
        if not adapter:
            interaction.write({'status': 'failed', 'error': 'no adapter registered'})
            return interaction.id
        try:
            result = adapter().send(self.env, interaction,
                                    {'body': text, 'options': [], 'media': []})
            interaction.write({
                'status': result.get('status', 'sent'),
                'source_model': result.get('source_model'),
                'source_id': result.get('source_id'),
                'error': result.get('error'),
            })
        except Exception as e:  # pragma: no cover - provider-side failures
            _logger.warning('cx agent reply send failed (interaction %s): %s',
                            interaction.id, e)
            interaction.write({'status': 'failed', 'error': str(e)})
        return interaction.id


class CommInteraction(models.Model):
    _inherit = 'comm.interaction'

    channel_code = fields.Char(
        related='channel_id.code', string='Channel Code')
    # A playable recording for call interactions (VoIP): resolved from the
    # source call's attachment so the inbox can render an <audio> control.
    recording_url = fields.Char(compute='_compute_recording', string='Recording URL')
    recording_duration = fields.Char(compute='_compute_recording', string='Recording Duration')

    @api.depends('source_model', 'source_id')
    def _compute_recording(self):
        Att = self.env['ir.attachment'].sudo()
        for it in self:
            url = dur = False
            if it.source_model == 'comm.voip.call' and it.source_id:
                att = Att.search([
                    ('res_model', '=', 'comm.voip.call'),
                    ('res_id', '=', it.source_id),
                    ('res_field', '=', 'recording_ids'),
                ], order='id desc', limit=1)
                if att:
                    url = '/voip/call/recording/%s' % att.id
                    dur = att.recording_duration_display
            it.recording_url = url
            it.recording_duration = dur

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Nudge every open inbox to reload the affected conversation, and
        # enqueue any matching webhooks. Both are best-effort — a bus hiccup or
        # webhook-config issue must never block message creation, and the
        # webhook enqueue only writes cheap DB rows (the cron does the HTTP).
        bus = self.env['bus.bus']
        Webhook = self.env['cx.integration.webhook']
        for rec in records:
            try:
                bus._sendone(CX_INBOX_BUS_CHANNEL, 'cx_inbox_new_interaction',
                             {'conversation_id': rec.conversation_id.id})
            except Exception:  # pragma: no cover
                _logger.debug('cx_inbox bus notify skipped for interaction %s',
                              rec.id)
            try:
                event_code = ('interaction.inbound' if rec.direction == 'inbound'
                              else 'interaction.outbound')
                Webhook._cx_enqueue_event(event_code, {
                    'event': event_code,
                    'interaction_id': rec.id,
                    'conversation_id': rec.conversation_id.id,
                    'direction': rec.direction,
                    'channel': rec.channel_id.code or None,
                    'body': rec.rendered_body or rec.raw_body or '',
                    'at': rec.at and fields.Datetime.to_string(rec.at),
                })
            except Exception:  # pragma: no cover
                _logger.debug('cx webhook enqueue skipped for interaction %s', rec.id)
        return records
