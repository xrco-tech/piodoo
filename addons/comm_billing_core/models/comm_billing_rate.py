# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

from .comm_billing_rate_card import CHANNEL_SELECTION


CATEGORY_SELECTION = [
    # WhatsApp
    ('marketing',          'WA / Marketing'),
    ('utility',            'WA / Utility'),
    ('authentication',     'WA / Authentication'),
    ('auth_international', 'WA / Authentication-International'),
    ('service',            'WA / Service (non-template)'),
    ('mba_token',          'WA / MBA Token'),
    ('call_minute',        'WA / Call minute'),
    # SMS
    ('sms_outbound_domestic', 'SMS / Outbound domestic'),
    ('sms_outbound_intl',     'SMS / Outbound international'),
    ('sms_inbound',           'SMS / Inbound'),
    ('sms_two_way',           'SMS / Two-way'),
    ('sms_premium',           'SMS / Premium (short code)'),
    # USSD
    ('ussd_session',      'USSD / Session'),
    ('ussd_push',         'USSD / Push (per node)'),
    # Voice
    ('voice_inbound',              'Voice / Inbound'),
    ('voice_outbound_local_mobile','Voice / Outbound local mobile'),
    ('voice_outbound_local_fixed', 'Voice / Outbound local fixed-line'),
    ('voice_outbound_intl',        'Voice / Outbound international'),
]

UNIT_SELECTION = [
    ('message',      'per message'),
    ('segment',      'per SMS segment'),
    ('session',      'per USSD session'),
    ('minute',       'per minute'),
    ('kilotoken',    'per 1,000 tokens'),
    ('conversation', 'per conversation (legacy)'),
]

DIRECTION_SELECTION = [
    ('inbound',  'Inbound'),
    ('outbound', 'Outbound'),
    ('any',      'Any'),
]


class CommBillingRate(models.Model):
    _name = 'comm.billing.rate'
    _description = 'Communication billing rate row'
    _order = 'card_id, channel, country_id, category, carrier, tier_from'

    card_id = fields.Many2one('comm.billing.rate.card', required=True,
                              ondelete='cascade', index=True)
    channel = fields.Selection(CHANNEL_SELECTION, related='card_id.channel',
                               store=True, index=True)
    country_id = fields.Many2one('res.country', index=True,
        help='Destination country. Leave empty for global rates.')
    category = fields.Selection(CATEGORY_SELECTION, required=True, index=True)
    carrier = fields.Char(index=True,
        help='Optional carrier / provider / MNO name (e.g. MTN, Vodacom). '
             'Leave empty to match any carrier.')
    direction = fields.Selection(DIRECTION_SELECTION, default='any', index=True)
    unit = fields.Selection(UNIT_SELECTION, required=True, default='message')
    price_usd = fields.Float(required=True, digits=(12, 6),
        help='Rate in USD per unit.')
    tier_from = fields.Integer(default=0,
        help='Cumulative monthly volume at which this tier starts.')
    tier_to = fields.Integer(default=0,
        help='Cumulative monthly volume at which this tier ends. 0 = no upper bound.')
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('card_id.name', 'country_id.code', 'category', 'carrier',
                 'direction', 'tier_from', 'price_usd')
    def _compute_display_name(self):
        for rec in self:
            country = rec.country_id.code or 'GLOBAL'
            carrier = f'/{rec.carrier}' if rec.carrier else ''
            direction = f'/{rec.direction}' if rec.direction and rec.direction != 'any' else ''
            tier = f' [{rec.tier_from}+]' if rec.tier_from else ''
            rec.display_name = (f'{country}{carrier}{direction} / {rec.category}'
                                f'{tier} @ ${rec.price_usd:.4f}')

    @api.constrains('tier_from', 'tier_to')
    def _check_tiers(self):
        for rec in self:
            if rec.tier_to and rec.tier_from >= rec.tier_to:
                raise ValidationError('tier_from must be less than tier_to.')
