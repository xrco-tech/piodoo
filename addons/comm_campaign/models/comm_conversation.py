# -*- coding: utf-8 -*-
"""Attribute campaign spend + conversions back to the send row."""
import logging
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CommConversation(models.Model):
    _inherit = 'comm.conversation'

    def write(self, vals):
        res = super().write(vals)
        # When a conversation closes with an outcome, attribute
        if 'lifecycle_state' in vals or 'outcome' in vals:
            for c in self:
                if c.lifecycle_state in ('closed',) and c.outcome:
                    c._attribute_to_campaign_send()
        return res

    def _attribute_to_campaign_send(self):
        """Find a matching campaign.send and mark conversion + roll up cost."""
        self.ensure_one()
        Send = self.env['comm.campaign.send']
        # Direct link case (opened by campaign)
        send = Send.search([
            ('conversation_id', '=', self.id),
        ], limit=1)
        if not send and self.campaign_id:
            # Find recent send for this partner + campaign
            window = timedelta(hours=72)
            send = Send.search([
                ('partner_id', '=', self.partner_id.id),
                ('sent_at', '>=', fields.Datetime.now() - window),
                ('campaign_id', '=', int(self.campaign_id)) if self.campaign_id.isdigit() else False,
            ], limit=1)
        if not send:
            return

        # Mark conversion if outcome is a positive tag
        conversion_tags = {'completed', 'success', 'converted', 'done', 'canary_done'}
        if (self.outcome or '').lower() in conversion_tags:
            send.conversion_registered = True

        # Roll up billing cost
        events = self.env['comm.billing.event'].search([
            ('conversation_id', '=', self.id),
        ])
        send.write({
            'billed_usd': sum(events.mapped('price_usd')),
            'billed_local': sum(events.mapped('price_local')),
        })

    @api.model
    def cron_purge_walker_previews(self):
        """Delete walker preview conversations older than 1 hour."""
        cutoff = fields.Datetime.now() - timedelta(hours=1)
        stale = self.search([
            ('outcome', '=', '__preview_walker__'),
            ('create_date', '<', cutoff),
        ], limit=500)
        stale.sudo().unlink()
