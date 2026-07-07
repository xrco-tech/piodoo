# -*- coding: utf-8 -*-
import logging
from datetime import time, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


SEND_STATUS_SELECTION = [
    ('queued',       'Queued'),
    ('deferred',     'Deferred (quiet hours / retry)'),
    ('sent',         'Sent'),
    ('delivered',    'Delivered'),
    ('failed',       'Failed'),
    ('skipped',      'Skipped (unreachable / opted out)'),
    ('skipped_budget', 'Skipped (budget exceeded)'),
]


class CommCampaignSend(models.Model):
    _name = 'comm.campaign.send'
    _description = 'One recipient send within a campaign'
    _order = 'campaign_id, sent_at desc, id'
    _rec_name = 'display_name'

    campaign_id = fields.Many2one('comm.campaign', required=True,
                                   ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', required=True, index=True)
    variant_id = fields.Many2one('comm.campaign.variant')
    chosen_channel_id = fields.Many2one('comm.channel')
    status = fields.Selection(SEND_STATUS_SELECTION, default='queued',
                              required=True, index=True)
    scheduled_at = fields.Datetime(index=True,
        help='When to attempt this send. Set by quiet-hours deferrals.')
    sent_at = fields.Datetime()
    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=3)
    error = fields.Text()
    skip_reason = fields.Char()

    conversation_id = fields.Many2one('comm.conversation',
        help='The conversation this send opened.')
    conversion_registered = fields.Boolean(
        help='True when the conversation ended with a success outcome.')

    billed_usd = fields.Float(digits=(12, 4), default=0.0)
    billed_local = fields.Float(digits=(12, 2), default=0.0)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('campaign_id.name', 'partner_id.name', 'status')
    def _compute_display_name(self):
        for s in self:
            s.display_name = f'{s.campaign_id.name} → {s.partner_id.name} [{s.status}]'

    # ---------- Send processing ----------
    def _process(self):
        for send in self:
            try:
                send._process_one()
            except Exception as e:
                _logger.warning('Campaign send %s failed: %s', send.id, e)
                send.write({'status': 'failed', 'error': str(e)})

    def _process_one(self):
        """Resolve channel, check consent + quiet hours + budget, launch bot."""
        campaign = self.campaign_id

        # 1. Budget check
        budget_state = campaign._check_budget()
        if budget_state == 'exceeded' and campaign.hard_stop_at_cap:
            campaign._notify_budget('exceeded')
            self.write({'status': 'skipped_budget'})
            return
        if budget_state in ('warn', 'exceeded'):
            campaign._notify_budget(budget_state)

        # 2. Channel resolution
        channel, skip_reason = self._resolve_channel()
        if not channel:
            self.write({'status': 'skipped', 'skip_reason': skip_reason})
            return

        # 3. Launch bot on chosen channel
        bot = self.variant_id.bot_id if self.variant_id else campaign.bot_id
        conversation = self.env['comm.chatbot.executor'].start(
            bot, self.partner_id, channel.code, campaign_id=str(campaign.id))
        if not conversation:
            self.write({'status': 'failed', 'error': 'bot start failed'})
            return

        self.write({
            'status': 'sent',
            'chosen_channel_id': channel.id,
            'sent_at': fields.Datetime.now(),
            'conversation_id': conversation.id,
        })

    def _resolve_channel(self):
        """Return (channel, skip_reason_or_None)."""
        campaign = self.campaign_id
        Registry = self.env['comm.chatbot.registry']
        Pref = self.env['comm.partner.communication.preference']
        for channel in campaign.channel_priority_ids.sorted('sequence'):
            adapter_cls = Registry.get_adapter_for_channel(channel)
            if not adapter_cls:
                continue
            try:
                adapter = adapter_cls()
                if not adapter.can_reach(self.env, self.partner_id):
                    continue
            except Exception as e:
                _logger.debug('can_reach failed for %s: %s', channel.code, e)
                continue
            if not Pref.is_opted_in(self.partner_id, channel, campaign.purpose):
                continue
            if campaign.respect_quiet_hours and self._is_quiet_hours(channel):
                # Defer to next permitted window
                next_at = self._next_permitted_window(channel)
                self.write({'status': 'deferred', 'scheduled_at': next_at})
                return None, None
            return channel, None
        return None, 'no reachable channel'

    def _is_quiet_hours(self, channel):
        # Get partner tz
        tz_name = self._get_partner_tz()
        try:
            import pytz
            now = fields.Datetime.now().replace(tzinfo=pytz.UTC).astimezone(pytz.timezone(tz_name))
        except Exception:
            now = fields.Datetime.now()
        start_h = channel.quiet_hours_start or 8
        end_h = channel.quiet_hours_end or 20
        # Weekend check
        if now.weekday() >= 5 and not self.campaign_id.send_on_weekends:
            return True
        current_h = now.hour + now.minute / 60.0
        return not (start_h <= current_h < end_h)

    def _next_permitted_window(self, channel):
        tz_name = self._get_partner_tz()
        try:
            import pytz
            local = fields.Datetime.now().replace(tzinfo=pytz.UTC).astimezone(pytz.timezone(tz_name))
        except Exception:
            local = fields.Datetime.now()
        start_h = int(channel.quiet_hours_start or 8)
        # Next day's start
        next_local = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
        if next_local <= local:
            next_local = next_local + timedelta(days=1)
        # Skip weekends if configured
        while (next_local.weekday() >= 5 and
               not self.campaign_id.send_on_weekends):
            next_local = next_local + timedelta(days=1)
        try:
            import pytz
            return next_local.astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception:
            return next_local

    def _get_partner_tz(self):
        campaign = self.campaign_id
        if campaign.partner_timezone_source == 'partner':
            return self.partner_id.tz or self.env.company.tz or 'UTC'
        if campaign.partner_timezone_source == 'company':
            return self.env.company.tz or 'UTC'
        return 'UTC'
