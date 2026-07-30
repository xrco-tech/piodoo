# -*- coding: utf-8 -*-
"""Fire the `campaign.sent` webhook event when a campaign finishes sending.

comm_campaign flips state to 'completed' inside _process_batch once every send
is done. A write() override is the path-agnostic hook: it catches the
transition into 'completed' however it's reached (batch cron or manual), and
enqueues one webhook delivery per campaign — no HTTP here, the dispatch cron
does the POST.
"""
from odoo import models


class CommCampaign(models.Model):
    _inherit = 'comm.campaign'

    def write(self, vals):
        newly_completed = self.browse()
        if vals.get('state') == 'completed':
            newly_completed = self.filtered(lambda c: c.state != 'completed')
        res = super().write(vals)
        for campaign in newly_completed:
            self.env['cx.integration.webhook']._cx_enqueue_event('campaign.sent', {
                'event': 'campaign.sent',
                'campaign_id': campaign.id,
                'name': campaign.name,
                'audience_count': campaign.audience_count,
            })
        return res
