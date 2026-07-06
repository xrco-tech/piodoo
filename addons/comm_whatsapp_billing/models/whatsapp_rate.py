# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


CATEGORY_SELECTION = [
    ('marketing',          'Marketing'),
    ('utility',            'Utility'),
    ('authentication',     'Authentication'),
    ('auth_international', 'Authentication-International'),
    ('service',            'Service (non-template)'),
    ('mba_token',          'MBA Token (AI interaction)'),
    ('call_minute',        'Call minute'),
]

UNIT_SELECTION = [
    ('message',      'per message'),
    ('minute',       'per minute'),
    ('kilotoken',    'per 1,000 tokens'),
    ('conversation', 'per conversation (legacy)'),
]


class WhatsappRate(models.Model):
    _name = 'whatsapp.rate'
    _description = 'WhatsApp Rate (country x category x volume tier)'
    _order = 'card_id, country_id, category, tier_from'

    card_id = fields.Many2one('whatsapp.rate.card', required=True,
                              ondelete='cascade', index=True)
    country_id = fields.Many2one('res.country', index=True,
        help='Destination country. Leave empty for global rates (e.g. MBA tokens).')
    category = fields.Selection(CATEGORY_SELECTION, required=True, index=True)
    unit = fields.Selection(UNIT_SELECTION, required=True, default='message')
    price_usd = fields.Float(required=True, digits=(12, 6),
        help='Rate in USD per unit (message, minute, or 1k tokens).')
    tier_from = fields.Integer(default=0,
        help='Cumulative monthly volume at which this tier starts.')
    tier_to = fields.Integer(default=0,
        help='Cumulative monthly volume at which this tier ends. 0 = no upper bound.')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('card_id.name', 'country_id.code', 'category', 'tier_from')
    def _compute_display_name(self):
        for rec in self:
            country = rec.country_id.code or 'GLOBAL'
            tier = f' [{rec.tier_from}+]' if rec.tier_from else ''
            rec.display_name = f'{country} / {rec.category}{tier} @ ${rec.price_usd:.4f}'

    @api.constrains('tier_from', 'tier_to')
    def _check_tiers(self):
        for rec in self:
            if rec.tier_to and rec.tier_from >= rec.tier_to:
                raise ValidationError('tier_from must be less than tier_to.')
