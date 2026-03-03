# -*- coding: utf-8 -*-

import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ContactCentreCampaign(models.Model):
    _name = 'contact.centre.campaign'
    _description = 'Contact Centre Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char('Campaign Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    description = fields.Text('Description')
    campaign_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], 'Type', required=True, tracking=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('both', 'WhatsApp & SMS'),
    ], 'Channel', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], 'Status', default='draft', tracking=True)
    date_start = fields.Datetime('Start Date', tracking=True)
    date_end = fields.Datetime('End Date', tracking=True)

    contact_ids = fields.Many2many(
        'contact.centre.contact',
        'contact_centre_campaign_contact_rel',
        'campaign_id',
        'contact_id',
        string='Contacts',
    )
    message_ids = fields.One2many(
        'contact.centre.message',
        'campaign_id',
        string='Messages',
    )
    template_id = fields.Many2one(
        'contact.centre.template',
        'Message Template',
        domain="[('channel', '=', channel)]",
    )
    script_id = fields.Many2one(
        'contact.centre.script',
        'Agent Script',
    )
    automation_ids = fields.One2many(
        'contact.centre.automation',
        'campaign_id',
        string='Automated Replies',
    )

    # -------------------------------------------------------------------------
    # Sending configuration
    # -------------------------------------------------------------------------

    throttle_delay = fields.Float(
        'Message Delay (s)', default=0.5,
        help='Seconds to wait between sending each individual message. '
             'Use this to avoid carrier rate-limiting. Set 0 to disable.',
    )
    batch_send = fields.Boolean(
        'Send in Batches', default=False,
        help='When enabled, messages are sent in batches. '
             'The cron pauses between batches for the Batch Delay time.',
    )
    batch_size = fields.Integer(
        'Batch Size', default=50,
        help='Number of messages to send per batch. '
             'Only applies when "Send in Batches" is enabled.',
    )
    batch_delay = fields.Float(
        'Batch Delay (s)', default=60.0,
        help='Seconds to wait between batches. '
             'Only applies when "Send in Batches" is enabled.',
    )

    # -------------------------------------------------------------------------
    # Send progress tracking (stored, not computed)
    # -------------------------------------------------------------------------

    send_progress = fields.Integer(
        'Contacts Sent', default=0, readonly=True, copy=False,
        help='Number of contacts that have been messaged in this campaign run.',
    )
    send_last_batch_at = fields.Datetime(
        'Last Batch At', readonly=True, copy=False,
        help='Timestamp of the last batch that was dispatched.',
    )

    # -------------------------------------------------------------------------
    # Computed stats
    # -------------------------------------------------------------------------

    contact_count = fields.Integer('Contacts', compute='_compute_counts')
    message_count = fields.Integer('Messages', compute='_compute_counts')
    sent_count = fields.Integer('Sent', compute='_compute_counts')
    delivered_count = fields.Integer('Delivered', compute='_compute_counts')
    failed_count = fields.Integer('Failed', compute='_compute_counts')

    @api.depends('contact_ids', 'message_ids', 'message_ids.status')
    def _compute_counts(self):
        for campaign in self:
            campaign.contact_count = len(campaign.contact_ids)
            campaign.message_count = len(campaign.message_ids)
            campaign.sent_count = len(campaign.message_ids.filtered(
                lambda m: m.status in ('sent', 'delivered', 'read')))
            campaign.delivered_count = len(campaign.message_ids.filtered(
                lambda m: m.status in ('delivered', 'read')))
            campaign.failed_count = len(campaign.message_ids.filtered(
                lambda m: m.status == 'failed'))

    # -------------------------------------------------------------------------
    # State machine
    # -------------------------------------------------------------------------

    def action_start(self):
        self.ensure_one()
        if self.campaign_type == 'outbound':
            if not self.template_id:
                raise UserError(
                    "Please set a Message Template before starting an outbound campaign."
                )
            if not self.contact_ids:
                raise UserError(
                    "Please add contacts to the campaign before starting."
                )
        self.write({
            'state': 'running',
            'date_start': fields.Datetime.now(),
            'send_progress': 0,
            'send_last_batch_at': False,
        })

    def action_done(self):
        self.write({'state': 'done', 'date_end': fields.Datetime.now()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({
            'state': 'draft',
            'date_start': False,
            'date_end': False,
            'send_progress': 0,
            'send_last_batch_at': False,
        })

    # -------------------------------------------------------------------------
    # Smart button actions
    # -------------------------------------------------------------------------

    def action_view_contacts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campaign Contacts',
            'res_model': 'contact.centre.contact',
            'view_mode': 'list,form',
            'domain': [('campaign_ids', 'in', [self.id])],
            'context': {
                'default_campaign_ids': [(4, self.id)],
            },
        }

    def action_view_sent(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sent Messages',
            'res_model': 'contact.centre.message',
            'view_mode': 'list,form',
            'domain': [
                ('campaign_id', '=', self.id),
                ('status', 'in', ('sent', 'delivered', 'read')),
            ],
            'context': {'default_campaign_id': self.id},
        }

    def action_view_delivered(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Delivered Messages',
            'res_model': 'contact.centre.message',
            'view_mode': 'list,form',
            'domain': [
                ('campaign_id', '=', self.id),
                ('status', 'in', ('delivered', 'read')),
            ],
            'context': {'default_campaign_id': self.id},
        }

    def action_view_failed(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Failed Messages',
            'res_model': 'contact.centre.message',
            'view_mode': 'list,form',
            'domain': [
                ('campaign_id', '=', self.id),
                ('status', '=', 'failed'),
            ],
            'context': {'default_campaign_id': self.id},
        }

    # -------------------------------------------------------------------------
    # Background send engine
    # -------------------------------------------------------------------------

    @api.model
    def _cron_process_campaign_sends(self):
        """
        Scheduled action: pick up all running outbound campaigns that still
        have contacts to send to, and dispatch the next batch for each.
        """
        campaigns = self.search([
            ('state', '=', 'running'),
            ('campaign_type', '=', 'outbound'),
            ('template_id', '!=', False),
        ])
        for campaign in campaigns:
            if campaign.send_progress < len(campaign.contact_ids):
                try:
                    campaign.sudo()._send_next_batch()
                except Exception as e:
                    _logger.error(
                        "Campaign %s (%s) send error: %s",
                        campaign.name, campaign.id, e, exc_info=True,
                    )

    def _send_next_batch(self):
        """
        Send the next batch of messages for this campaign.

        Respects:
        - batch_delay: skips execution if not enough time has passed since the
          last batch (the cron will retry on the next tick).
        - batch_size: limits how many contacts are processed per cron tick
          when batch_send is enabled.
        - throttle_delay: sleeps between individual sends within a batch.
        """
        self.ensure_one()
        contacts = list(self.contact_ids)
        total = len(contacts)
        start_idx = self.send_progress

        if start_idx >= total:
            self.action_done()
            return

        # Enforce batch delay (skip if it's too soon for the next batch)
        if self.batch_send and self.send_last_batch_at:
            elapsed = (fields.Datetime.now() - self.send_last_batch_at).total_seconds()
            if elapsed < self.batch_delay:
                _logger.info(
                    "Campaign %s: batch delay not elapsed (%.0fs / %.0fs), skipping.",
                    self.name, elapsed, self.batch_delay,
                )
                return

        # Determine how many contacts to process this tick
        if self.batch_send and self.batch_size > 0:
            end_idx = min(start_idx + self.batch_size, total)
        else:
            end_idx = total  # send all in one go (throttle applies between each)

        batch = contacts[start_idx:end_idx]
        sent_in_batch = 0

        for i, contact in enumerate(batch):
            if i > 0 and self.throttle_delay > 0:
                time.sleep(self.throttle_delay)
            try:
                self._send_to_contact(contact)
            except Exception as e:
                _logger.error(
                    "Campaign %s: failed to send to contact %s: %s",
                    self.name, contact.id, e,
                )
            sent_in_batch += 1

        new_progress = start_idx + sent_in_batch
        self.write({
            'send_progress': new_progress,
            'send_last_batch_at': fields.Datetime.now(),
        })

        _logger.info(
            "Campaign %s: sent batch %d–%d of %d total.",
            self.name, start_idx + 1, new_progress, total,
        )

        if new_progress >= total:
            self.action_done()

    def _send_to_contact(self, contact):
        """Dispatch a message to a single contact on the configured channel(s)."""
        body = self.template_id.body_text or ''
        channel = self.channel

        if channel in ('whatsapp', 'both'):
            self._send_whatsapp(contact, body)
        if channel in ('sms', 'both'):
            self._send_sms(contact, body)
        if channel == 'email':
            self._send_email(contact, body)

    def _send_whatsapp(self, contact, body):
        phone = contact.phone_number
        if not phone:
            _logger.warning("Campaign %s: contact %s has no phone number, skipping WA.", self.name, contact.id)
            return

        result = self.env['whatsapp.message'].sudo().send_whatsapp_message(
            recipient_phone=phone,
            message_text=body,
        )
        success = isinstance(result, dict) and result.get('success', False)
        status = 'sent' if success else 'failed'
        failure = result.get('error', '') if isinstance(result, dict) and not success else ''

        self.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'campaign_id': self.id,
            'channel': 'whatsapp',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'provider_message_id': result.get('message_id', '') if isinstance(result, dict) else '',
            'template_id': self.template_id.id,
            'message_timestamp': fields.Datetime.now(),
        })

    def _send_sms(self, contact, body):
        phone = contact.phone_number
        if not phone:
            _logger.warning("Campaign %s: contact %s has no phone number, skipping SMS.", self.name, contact.id)
            return

        sms = self.env['sms.sms'].sudo().create({
            'number': phone,
            'body': body,
            'state': 'outgoing',
        })
        try:
            sms._send()
            status = 'sent'
            failure = ''
        except Exception as e:
            status = 'failed'
            failure = str(e)

        self.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'campaign_id': self.id,
            'channel': 'sms',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'sms_id': sms.id,
            'template_id': self.template_id.id,
            'message_timestamp': fields.Datetime.now(),
        })

    def _send_email(self, contact, body):
        email = contact.email
        if not email:
            _logger.warning("Campaign %s: contact %s has no email, skipping.", self.name, contact.id)
            return

        mail = self.env['mail.mail'].sudo().create({
            'subject': self.name,
            'body_html': '<p>%s</p>' % body,
            'email_to': email,
            'auto_delete': False,
        })
        try:
            mail.send()
            status = 'sent'
            failure = ''
        except Exception as e:
            status = 'failed'
            failure = str(e)

        self.env['contact.centre.message'].sudo().create({
            'contact_id': contact.id,
            'campaign_id': self.id,
            'channel': 'email',
            'direction': 'outbound',
            'message_type': 'text',
            'body_text': body,
            'status': status,
            'failure_reason': failure,
            'template_id': self.template_id.id,
            'message_timestamp': fields.Datetime.now(),
        })
