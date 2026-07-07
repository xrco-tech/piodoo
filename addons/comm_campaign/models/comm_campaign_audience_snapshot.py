# -*- coding: utf-8 -*-
from odoo import models, fields


class CommCampaignAudienceSnapshot(models.Model):
    _name = 'comm.campaign.audience.snapshot'
    _description = 'Frozen audience list for a static campaign'
    _order = 'campaign_id, partner_id'

    campaign_id = fields.Many2one('comm.campaign', required=True,
                                   ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', required=True, index=True)
    added_at = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('campaign_partner_uniq', 'unique(campaign_id, partner_id)',
         'Partner already in this campaign audience.'),
    ]
