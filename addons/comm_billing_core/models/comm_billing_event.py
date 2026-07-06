# -*- coding: utf-8 -*-
"""Unified billing event ledger.

Every billable action across every channel lands here. Channel-specific
modules (comm_whatsapp_billing, comm_sms_billing, etc.) create rows via
`_create_from_source()` or the specific `_create_from_*` helpers they add
via inherits.
"""
import logging
import phonenumbers
from odoo import models, fields, api

from .comm_billing_rate_card import CHANNEL_SELECTION
from .comm_billing_rate import (CATEGORY_SELECTION, UNIT_SELECTION,
                                 DIRECTION_SELECTION)

_logger = logging.getLogger(__name__)


class CommBillingEvent(models.Model):
    _name = 'comm.billing.event'
    _description = 'Communication billing event (message / segment / session / minute)'
    _order = 'event_date desc, id desc'
    _rec_name = 'display_name'

    event_date = fields.Datetime(required=True, default=fields.Datetime.now,
                                 index=True)
    channel = fields.Selection(CHANNEL_SELECTION, required=True, index=True)
    provider = fields.Char(index=True)
    account_ref = fields.Char(index=True,
        help='Free-text originating account identifier (channel-specific).')
    partner_id = fields.Many2one('res.partner', index=True)
    wa_id = fields.Char(index=True,
        help='Destination MSISDN / WhatsApp ID.')
    country_id = fields.Many2one('res.country', index=True)
    carrier = fields.Char(index=True)
    direction = fields.Selection(DIRECTION_SELECTION, index=True)
    category = fields.Selection(CATEGORY_SELECTION, required=True, index=True)
    unit = fields.Selection(UNIT_SELECTION, required=True, default='message')
    unit_qty = fields.Float(required=True, default=1.0)

    rate_card_id = fields.Many2one('comm.billing.rate.card', readonly=True)
    rate_id = fields.Many2one('comm.billing.rate', readonly=True)
    price_usd = fields.Float(readonly=True, digits=(12, 6))
    fx_rate = fields.Float(readonly=True, digits=(12, 6), default=1.0)
    price_local = fields.Float(readonly=True, digits=(12, 4))
    currency_id = fields.Many2one('res.currency', readonly=True)

    is_free = fields.Boolean(readonly=True, index=True)
    free_reason = fields.Char(readonly=True)

    source_model = fields.Char(index=True, readonly=True)
    source_id = fields.Integer(index=True, readonly=True)
    campaign_id = fields.Char(index=True)

    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('event_source_uniq', 'unique(source_model, source_id, category, unit)',
         'A billing event for this source record already exists.'),
    ]

    @api.depends('event_date', 'channel', 'category', 'price_usd', 'unit_qty')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (f'{rec.event_date} [{rec.channel}] '
                                f'{rec.category} {rec.unit_qty:.2f}{rec.unit or ""} '
                                f'${rec.price_usd:.4f}')

    # ---- MSISDN → country ----
    @api.model
    def _country_from_wa_id(self, wa_id):
        if not wa_id:
            return self.env['res.country']
        try:
            num = phonenumbers.parse('+' + str(wa_id).lstrip('+'))
            code = phonenumbers.region_code_for_number(num)
            if code:
                return self.env['res.country'].search([('code', '=', code)], limit=1)
        except Exception as e:
            _logger.debug('phonenumbers parse failed for %s: %s', wa_id, e)
        return self.env['res.country']

    # ---- Volume tier lookup ----
    @api.model
    def _month_to_date_qty(self, channel, country, category, on_date):
        start = fields.Date.to_date(on_date).replace(day=1)
        return self.search_count([
            ('channel', '=', channel),
            ('country_id', '=', country.id if country else False),
            ('category', '=', category),
            ('event_date', '>=', fields.Datetime.to_datetime(start)),
            ('event_date', '<=', on_date),
        ])

    # ---- FX resolver ----
    @api.model
    def _resolve_fx(self, provider, event_date, currency_hint=None):
        """Return (fx_rate, currency). Priority: provider monthly override →
        Odoo res.currency.rate → 1.0/USD fallback."""
        USD = self.env.ref('base.USD', raise_if_not_found=False)
        company = self.env.company
        currency = currency_hint or company.currency_id or USD

        if not currency or (USD and currency.id == USD.id):
            return 1.0, currency or USD

        fx = self.env['comm.billing.fx.rate']._rate_for_month(
            currency, event_date, provider=provider)
        if fx:
            return fx, currency

        if USD:
            try:
                as_date = fields.Date.to_date(event_date) if event_date else fields.Date.today()
                fx = USD._convert(1.0, currency, company, as_date, round=False)
                if fx and fx != 1.0:
                    return fx, currency
            except Exception as e:
                _logger.debug('_convert failed: %s', e)

        _logger.warning('No FX USD->%s for %s (provider=%s). Storing in USD.',
                        currency.name, event_date, provider or '?')
        return 1.0, USD or currency

    # ---- Core pricing engine ----
    @api.model
    def _price(self, vals):
        event_date = vals.get('event_date') or fields.Datetime.now()
        channel = vals['channel']
        category = vals['category']
        unit_qty = vals.get('unit_qty', 1.0)
        provider = vals.get('provider')
        country = self.env['res.country'].browse(vals.get('country_id') or 0)
        wa_id = vals.get('wa_id')

        card = self.env['comm.billing.rate.card'].active_on(channel, event_date)
        if not card:
            vals.update(price_usd=0.0, price_local=0.0, fx_rate=1.0)
            return vals

        vals['rate_card_id'] = card.id

        # Free-window checks (WhatsApp only, driven by rate card flags)
        FreeWindow = self.env['comm.billing.free.window']
        is_free, free_reason = False, False
        account_ref = vals.get('account_ref')
        if channel == 'whatsapp' and wa_id:
            if category in ('service', 'utility'):
                if FreeWindow.covers(account_ref, wa_id, event_date, 'cs_24h'):
                    if category == 'service' and card.service_free_in_cs_window:
                        is_free, free_reason = True, 'cs_24h/service'
                    elif category == 'utility' and card.utility_free_in_cs_window:
                        is_free, free_reason = True, 'cs_24h/utility'
            if not is_free and category in ('marketing', 'utility',
                                            'authentication', 'service'):
                if FreeWindow.covers(account_ref, wa_id, event_date, 'entry_72h'):
                    is_free, free_reason = True, 'entry_72h'

        if is_free:
            _, currency = self._resolve_fx(provider, event_date)
            vals.update(is_free=True, free_reason=free_reason,
                        price_usd=0.0, price_local=0.0, fx_rate=1.0,
                        currency_id=currency.id if currency else False)
            return vals

        # Volume tier
        mtd = self._month_to_date_qty(channel, country, category, event_date)
        rate = card.resolve_rate(
            country=country, category=category,
            carrier=vals.get('carrier'),
            direction=vals.get('direction'),
            monthly_volume=mtd,
        )
        if not rate:
            _logger.warning('No rate: card=%s channel=%s country=%s '
                            'category=%s carrier=%s direction=%s',
                            card.name, channel, country.code or 'GLOBAL',
                            category, vals.get('carrier'), vals.get('direction'))
            vals.update(price_usd=0.0, price_local=0.0, fx_rate=1.0)
            return vals

        price_usd = unit_qty * rate.price_usd
        fx, currency = self._resolve_fx(provider, event_date)

        vals.update(
            rate_id=rate.id,
            price_usd=price_usd,
            fx_rate=fx,
            price_local=price_usd * fx,
            currency_id=currency.id if currency else False,
        )
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('country_id') and vals.get('wa_id'):
                country = self._country_from_wa_id(vals['wa_id'])
                if country:
                    vals['country_id'] = country.id
            self._price(vals)
        return super().create(vals_list)
