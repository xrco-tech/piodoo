# -*- coding: utf-8 -*-
"""Unified billing event ledger.

Every billable action across every channel lands here. Channel-specific
modules (comm_whatsapp_billing, comm_sms_billing, etc.) create rows via
`_create_from_source()` or the specific `_create_from_*` helpers they add
via inherits.
"""
import logging
import math
from datetime import timedelta

import phonenumbers
from odoo import models, fields, api

from .comm_billing_rate_card import CHANNEL_SELECTION
from .comm_billing_rate import (CATEGORY_SELECTION, UNIT_SELECTION,
                                 DIRECTION_SELECTION)

_logger = logging.getLogger(__name__)

# An Odoo currency rate older than this is not used to convert a charge.
ODOO_RATE_MAX_AGE_DAYS = 62


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
    source = fields.Selection(
        selection=[('chat2work', 'Chat2Work'),
                   ('contact_centre', 'Contact Centre'),
                   ('other', 'Not attributed')],
        string='Caused by', index=True,
        help='Which part of the business the charge belongs to. Worked out '
             'when the charge is recorded: the feature that made it says so, '
             'or else the person on the other end decides it.')
    feature = fields.Char(index=True,
        help='The feature that caused an AI charge, e.g. sidekick or copilot.')

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

    # ---- Who caused the charge ----
    @api.model
    def _source_of_person(self, partner_id, number):
        """Chat2Work when the person is one of its candidates, Contact Centre
        when they are one of its contacts, otherwise 'other'. A person who is
        both counts as Chat2Work: every WhatsApp sender is mirrored into the
        Contact Centre, so being a contact there says less.

        Neither app is a dependency of billing, hence the registry checks."""
        digits = ''.join(ch for ch in str(number or '') if ch.isdigit())
        numbers = [digits, '+' + digits] if digits else []
        lookups = (
            ('chat2work', 'chat2work.candidate', 'phone'),
            ('contact_centre', 'contact.centre.contact', 'phone_number'),
        )
        for source, model, phone_field in lookups:
            if model not in self.env:
                continue
            domain = []
            if partner_id:
                domain.append(('partner_id', '=', partner_id))
            if numbers:
                domain.append((phone_field, 'in', numbers))
            if not domain:
                continue
            if len(domain) == 2:
                domain = ['|'] + domain
            if self.env[model].sudo().search_count(domain, limit=1):
                return source
        return 'other'

    @api.model
    def _attribute(self, vals):
        """Fill `source` (and the campaign, when one sent the message)."""
        if (vals.get('source_model') == 'whatsapp.message' and vals.get('source_id')
                and 'contact.centre.message' in self.env
                and 'whatsapp.message' in self.env):
            message = self.env['whatsapp.message'].sudo().browse(vals['source_id']).exists()
            if message and message.message_id:
                sent = self.env['contact.centre.message'].sudo().search([
                    ('provider_message_id', '=', message.message_id),
                    ('campaign_id', '!=', False)], limit=1)
                if sent:
                    vals.setdefault('campaign_id', sent.campaign_id.display_name)
                    vals.setdefault('source', 'contact_centre')
        if not vals.get('source'):
            vals['source'] = self._source_of_person(vals.get('partner_id'), vals.get('wa_id'))
        # Whoever sends a message can say what it was for (e.g. a job alert).
        if not vals.get('feature') and self.env.context.get('billing_feature'):
            vals['feature'] = self.env.context['billing_feature']
        return vals

    @api.model
    def _backfill_source(self):
        """Attribute the charges recorded before `source` existed."""
        for event in self.sudo().search([('source', '=', False)]):
            vals = self._attribute({
                'source_model': event.source_model, 'source_id': event.source_id,
                'partner_id': event.partner_id.id, 'wa_id': event.wa_id,
                **({'campaign_id': event.campaign_id} if event.campaign_id else {}),
            })
            event.write({'source': vals['source'],
                         'campaign_id': vals.get('campaign_id') or False})

    # ---- AI usage ----
    @api.model
    def _log_llm_usage(self, model, usage, source=False, feature=False, partner=None):
        """Record what one call to the AI cost, from the `usage` block of its
        answer. Never raises: a billing problem must not break the feature."""
        try:
            usage = usage or {}
            # Rates are keyed on the model family: drop a dated suffix (-20251001).
            parts = (model or '').rsplit('-', 1)
            carrier = parts[0] if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit() else model
            buckets = (
                ('llm_input', usage.get('input_tokens')),
                ('llm_output', usage.get('output_tokens')),
                ('llm_cache_read', usage.get('cache_read_input_tokens')),
                ('llm_cache_write', usage.get('cache_creation_input_tokens')),
            )
            vals_list = [{
                'channel': 'other', 'provider': 'Anthropic', 'carrier': carrier,
                'category': category, 'unit': 'kilotoken', 'unit_qty': tokens / 1000.0,
                'source': source or 'other', 'feature': feature or False,
                'partner_id': partner.id if partner else False,
            } for category, tokens in buckets if tokens]
            if not vals_list:
                return self.browse()
            with self.env.cr.savepoint():
                return self.sudo().create(vals_list)
        except Exception:
            _logger.exception('Could not record AI usage for %s/%s', source, feature)
            return self.browse()

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
                # Odoo ships a sample rate dated 2010 for most currencies. Only
                # trust its rate when someone has kept it reasonably current.
                recent = self.env['res.currency.rate'].sudo().search_count([
                    ('currency_id', '=', currency.id),
                    ('company_id', 'in', [company.id, False]),
                    ('name', '<=', as_date),
                    ('name', '>=', as_date - timedelta(days=ODOO_RATE_MAX_AGE_DAYS)),
                ], limit=1)
                if recent:
                    fx = USD._convert(1.0, currency, company, as_date, round=False)
                    if fx and fx != 1.0:
                        return fx, currency
            except Exception as e:
                _logger.debug('_convert failed: %s', e)

        _logger.warning('No FX USD->%s for %s (provider=%s). Storing in USD.',
                        currency.name, event_date, provider or '?')
        return 1.0, USD or currency

    @api.model
    def _blocks_20s(self, seconds):
        """How many 20-second blocks a USSD session of this length is charged
        as: every started block counts, and a session is never free."""
        return float(max(1, math.ceil(max(seconds or 0, 0) / 20.0)))

    @api.model
    def _fixed_price(self, amount, currency, provider, event_date):
        """A charge the provider fixes in its own currency: the amount stands
        as it is, and the dollar price follows from the month's rate (0 when
        there is no rate to work it out from)."""
        fx, found = self._resolve_fx(provider, event_date, currency_hint=currency)
        known = bool(found and found.id == currency.id and fx)
        return {
            'price_local': amount,
            'currency_id': currency.id,
            'fx_rate': fx if known else 1.0,
            'price_usd': amount / fx if known else 0.0,
        }

    def _reconvert(self):
        """Convert these charges again from their dollar price, at the rate
        that applies now. Used when a month's rate is entered or corrected.
        Returns how many charges changed."""
        changed = 0
        for event in self:
            rate = event.rate_id
            if rate.price_local and rate.local_currency_id and event.currency_id == rate.local_currency_id:
                # Fixed in rand (say): the amount stays, only its dollar price moves.
                vals = self._fixed_price(event.price_local, event.currency_id,
                                         event.provider, event.event_date)
                if abs(event.price_usd - vals['price_usd']) > 1e-6:
                    event.write(vals)
                    changed += 1
                continue
            fx, currency = self._resolve_fx(event.provider, event.event_date)
            vals = {
                'fx_rate': fx if event.price_usd else 1.0,
                'price_local': event.price_usd * fx,
                'currency_id': currency.id if currency else False,
            }
            if (abs(event.price_local - vals['price_local']) > 1e-6
                    or event.currency_id.id != vals['currency_id']):
                event.write(vals)
                changed += 1
        return changed

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

        card = self.env['comm.billing.rate.card'].active_on(channel, event_date, provider=provider)
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

        if rate.price_local and rate.local_currency_id:
            vals.update(rate_id=rate.id, **self._fixed_price(
                unit_qty * rate.price_local, rate.local_currency_id, provider, event_date))
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
            self._attribute(vals)
            self._price(vals)
        return super().create(vals_list)
