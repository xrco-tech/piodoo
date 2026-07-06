# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


CHANNEL_SELECTION = [
    ('whatsapp', 'WhatsApp'),
    ('sms',      'SMS'),
    ('ussd',     'USSD'),
    ('voice',    'Voice (non-WA)'),
    ('other',    'Other'),
]


class CommBillingRateCard(models.Model):
    _name = 'comm.billing.rate.card'
    _description = 'Communication billing rate card (versioned per channel)'
    _order = 'channel, effective_from desc, id desc'
    _rec_name = 'name'

    name = fields.Char(required=True)
    channel = fields.Selection(CHANNEL_SELECTION, required=True, index=True,
        default='whatsapp')
    provider = fields.Char(index=True,
        help='Optional provider tag (e.g. "Meta", "Infobip", "Africa\'s Talking").')
    effective_from = fields.Date(required=True, index=True)
    effective_to = fields.Date(index=True,
        help='Leave empty for the current active card.')
    billing_model = fields.Selection([
        # WhatsApp regimes
        ('conversation_pre_2025', 'WA per-conversation (legacy)'),
        ('per_message_2025',      'WA per-message (Jul 2025)'),
        ('hybrid_2026',           'WA per-message + MBA tokens (Aug 2026)'),
        ('hybrid_service_paid',   'WA hybrid + paid service (Oct 2026)'),
        # Generic
        ('per_segment',           'SMS per-segment'),
        ('per_session',           'USSD per-session'),
        ('per_minute',            'Voice per-minute'),
        ('generic',               'Generic'),
    ], required=True, default='generic')
    service_free_in_cs_window = fields.Boolean(
        default=False,
        help='WhatsApp: non-template service messages inside a 24h CS window '
             'are free. Ignored for non-WA channels.')
    utility_free_in_cs_window = fields.Boolean(
        default=False,
        help='WhatsApp: utility templates inside a 24h CS window are free.')
    rate_ids = fields.One2many('comm.billing.rate', 'card_id', string='Rates')
    active = fields.Boolean(default=True)
    notes = fields.Text()

    @api.constrains('effective_from', 'effective_to')
    def _check_dates(self):
        for card in self:
            if card.effective_to and card.effective_from > card.effective_to:
                raise ValidationError(
                    'Rate card effective_from must be <= effective_to.')

    @api.model
    def active_on(self, channel, on_date):
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.today()
        domain = [
            ('channel', '=', channel),
            ('active', '=', True),
            ('effective_from', '<=', on_date),
            '|', ('effective_to', '=', False), ('effective_to', '>=', on_date),
        ]
        card = self.search(domain, order='effective_from desc', limit=1)
        if not card:
            _logger.warning('No active %s rate card for %s', channel, on_date)
        return card

    def resolve_rate(self, country=None, category=None, carrier=None,
                     direction=None, monthly_volume=0):
        """Find the whatsapp.rate row that applies. Country-specific wins
        over global; carrier/direction filters are AND-matched when supplied."""
        self.ensure_one()
        Rate = self.env['comm.billing.rate']
        base = [
            ('card_id', '=', self.id),
            ('tier_from', '<=', monthly_volume),
            '|', ('tier_to', '=', 0), ('tier_to', '>', monthly_volume),
        ]
        if category:
            base.append(('category', '=', category))
        if carrier:
            base.append(('carrier', 'in', [carrier, False]))
        if direction:
            base.append(('direction', 'in', [direction, 'any', False]))

        # 1. Try country-specific
        if country:
            rate = Rate.search(base + [('country_id', '=', country.id)],
                               order='carrier desc nulls last, tier_from desc',
                               limit=1)
            if rate:
                return rate
        # 2. Fall back to global (country=null)
        return Rate.search(base + [('country_id', '=', False)],
                           order='carrier desc nulls last, tier_from desc',
                           limit=1)
