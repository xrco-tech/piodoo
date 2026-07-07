# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CommCampaignVariant(models.Model):
    _name = 'comm.campaign.variant'
    _description = 'Campaign A/B variant'
    _order = 'campaign_id, id'

    campaign_id = fields.Many2one('comm.campaign', required=True,
                                   ondelete='cascade', index=True)
    name = fields.Char(required=True)
    bot_id = fields.Many2one('comm.bot', required=True,
        help='Bot script for this variant. Falls back to campaign.bot_id if empty.')
    weight = fields.Integer(default=50, required=True,
        help='Relative weight (0-100). Sum across variants sets buckets.')
    is_control = fields.Boolean(help='Marks the control arm for reporting.')

    # Computed stats
    send_count = fields.Integer(compute='_compute_stats')
    delivered_count = fields.Integer(compute='_compute_stats')
    conversion_count = fields.Integer(compute='_compute_stats')
    conversion_rate = fields.Float(compute='_compute_stats', digits=(6, 2))
    cost_local = fields.Float(compute='_compute_stats', digits=(12, 2))

    @api.depends('campaign_id.send_ids.variant_id',
                 'campaign_id.send_ids.status',
                 'campaign_id.send_ids.conversion_registered')
    def _compute_stats(self):
        for v in self:
            sends = v.campaign_id.send_ids.filtered(lambda s: s.variant_id.id == v.id)
            v.send_count = len(sends)
            v.delivered_count = len(sends.filtered(
                lambda s: s.status in ('sent', 'delivered')))
            v.conversion_count = len(sends.filtered(
                lambda s: s.conversion_registered))
            v.conversion_rate = (
                (v.conversion_count / v.send_count * 100) if v.send_count else 0.0)
            v.cost_local = sum(sends.mapped('billed_local'))

    @api.constrains('weight')
    def _check_weight(self):
        for v in self:
            if v.weight < 0 or v.weight > 100:
                raise ValidationError('Variant weight must be between 0 and 100.')
