# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class WhatsappRateCard(models.Model):
    _name = 'whatsapp.rate.card'
    _description = 'WhatsApp Rate Card (versioned pricing regime)'
    _order = 'effective_from desc, id desc'
    _rec_name = 'name'

    name = fields.Char(required=True)
    effective_from = fields.Date(required=True, index=True)
    effective_to = fields.Date(index=True,
        help='Leave empty for the current active card.')
    billing_model = fields.Selection([
        ('conversation_pre_2025', 'Per-conversation (legacy, pre-Jul 2025)'),
        ('per_message_2025',      'Per-message (Jul 2025 onward)'),
        ('hybrid_2026',           'Per-message + MBA tokens (Aug 2026)'),
        ('hybrid_service_paid',   'Hybrid + paid service (Oct 2026)'),
    ], required=True, default='per_message_2025')
    service_free_in_cs_window = fields.Boolean(
        default=True,
        help='If enabled, non-template service messages inside an open 24h customer '
             'service window are billed at zero. Turn off for Oct 2026 regime.')
    utility_free_in_cs_window = fields.Boolean(
        default=True,
        help='Utility templates inside an open 24h CS window are free (per Jul 2025).')
    rate_ids = fields.One2many('whatsapp.rate', 'card_id', string='Rates')
    active = fields.Boolean(default=True)
    notes = fields.Text()

    @api.constrains('effective_from', 'effective_to')
    def _check_dates(self):
        for card in self:
            if card.effective_to and card.effective_from > card.effective_to:
                raise ValidationError(
                    'Rate card effective_from must be <= effective_to.')

    @api.model
    def active_on(self, on_date):
        on_date = fields.Date.to_date(on_date) if on_date else fields.Date.today()
        domain = [
            ('active', '=', True),
            ('effective_from', '<=', on_date),
            '|', ('effective_to', '=', False), ('effective_to', '>=', on_date),
        ]
        card = self.search(domain, order='effective_from desc', limit=1)
        if not card:
            _logger.warning('No active WhatsApp rate card for %s', on_date)
        return card

    def resolve_rate(self, country, category, monthly_volume=0):
        """Return the whatsapp.rate row that applies to this event.

        Falls back to global (country=null) rows for units like MBA tokens.
        """
        self.ensure_one()
        Rate = self.env['whatsapp.rate']
        base = [('card_id', '=', self.id), ('category', '=', category),
                ('tier_from', '<=', monthly_volume)]
        volume_ok = ['|', ('tier_to', '=', 0), ('tier_to', '>', monthly_volume)]
        # Country-specific first, then global
        if country:
            rate = Rate.search(base + volume_ok + [('country_id', '=', country.id)],
                               order='tier_from desc', limit=1)
            if rate:
                return rate
        return Rate.search(base + volume_ok + [('country_id', '=', False)],
                           order='tier_from desc', limit=1)
