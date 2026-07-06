# -*- coding: utf-8 -*-
import logging
import phonenumbers
from odoo import models, fields, api
from odoo.exceptions import UserError

from .whatsapp_rate import CATEGORY_SELECTION, UNIT_SELECTION

_logger = logging.getLogger(__name__)


class WhatsappBillingEvent(models.Model):
    _name = 'whatsapp.billing.event'
    _description = 'WhatsApp billing event (message, call minute, MBA token)'
    _order = 'event_date desc, id desc'
    _rec_name = 'display_name'

    event_date = fields.Datetime(required=True, default=fields.Datetime.now,
                                 index=True)
    account_id = fields.Many2one('comm.whatsapp.account', index=True,
        help='WABA account that sent/received. Drives currency + business country.')
    partner_id = fields.Many2one('res.partner', index=True)
    wa_id = fields.Char(index=True,
        help='Recipient WhatsApp ID / MSISDN.')
    country_id = fields.Many2one('res.country', index=True,
        help='Destination country (resolved from wa_id MSISDN prefix).')
    category = fields.Selection(CATEGORY_SELECTION, required=True, index=True)
    unit = fields.Selection(UNIT_SELECTION, required=True, default='message')
    unit_qty = fields.Float(required=True, default=1.0,
        help='1 for message, N for minutes, tokens/1000 for MBA.')

    rate_card_id = fields.Many2one('whatsapp.rate.card', readonly=True)
    rate_id = fields.Many2one('whatsapp.rate', readonly=True)
    price_usd = fields.Float(readonly=True, digits=(12, 6))
    fx_rate = fields.Float(readonly=True, digits=(12, 6), default=1.0)
    price_local = fields.Float(readonly=True, digits=(12, 4))
    currency_id = fields.Many2one('res.currency', readonly=True)

    is_free = fields.Boolean(readonly=True, index=True,
        help='True when covered by a free window (CS-24h / entry-72h).')
    free_reason = fields.Char(readonly=True)

    # Source refs (kept explicit rather than Reference so we can index)
    source_model = fields.Char(index=True, readonly=True)
    source_id = fields.Integer(index=True, readonly=True)
    message_id = fields.Many2one('whatsapp.message', index=True, ondelete='set null')
    campaign_id = fields.Char(index=True,
        help='Optional campaign tag for reporting.')

    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('event_source_uniq', 'unique(source_model, source_id, category, unit)',
         'A billing event for this source record already exists.'),
    ]

    @api.depends('event_date', 'category', 'price_usd', 'unit_qty')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (f'{rec.event_date} {rec.category} '
                                f'{rec.unit_qty:.2f}{rec.unit or ""} '
                                f'${rec.price_usd:.4f}')

    # ---- Country resolution from MSISDN ----
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

    # ---- Volume tier lookup (MTD, per account/country/category) ----
    @api.model
    def _month_to_date_qty(self, account, country, category, on_date):
        start = fields.Date.to_date(on_date).replace(day=1)
        return self.search_count([
            ('account_id', '=', account.id if account else False),
            ('country_id', '=', country.id if country else False),
            ('category', '=', category),
            ('event_date', '>=', fields.Datetime.to_datetime(start)),
            ('event_date', '<=', on_date),
        ])

    # ---- Core pricing engine ----
    @api.model
    def _price(self, vals):
        """Resolve rate card, rate, free windows, and populate price fields.
        Mutates and returns `vals`. Never raises for missing rate — logs and
        writes zero so ingestion never fails."""
        event_date = vals.get('event_date') or fields.Datetime.now()
        category = vals['category']
        unit_qty = vals.get('unit_qty', 1.0)

        account = self.env['comm.whatsapp.account'].browse(vals.get('account_id') or 0)
        country = self.env['res.country'].browse(vals.get('country_id') or 0)
        wa_id = vals.get('wa_id')

        card = self.env['whatsapp.rate.card'].active_on(event_date)
        if not card:
            vals.update(price_usd=0.0, price_local=0.0, fx_rate=1.0)
            return vals

        vals['rate_card_id'] = card.id

        # Free-window checks (skip for calls and tokens)
        FreeWindow = self.env['whatsapp.free.window']
        is_free, free_reason = False, False
        if category in ('service', 'utility') and wa_id:
            in_cs = FreeWindow.covers(account, wa_id, event_date, 'cs_24h')
            if in_cs:
                if category == 'service' and card.service_free_in_cs_window:
                    is_free, free_reason = True, 'cs_24h/service'
                elif category == 'utility' and card.utility_free_in_cs_window:
                    is_free, free_reason = True, 'cs_24h/utility'
        if not is_free and wa_id and category in ('marketing', 'utility',
                                                  'authentication', 'service'):
            if FreeWindow.covers(account, wa_id, event_date, 'entry_72h'):
                is_free, free_reason = True, 'entry_72h'

        if is_free:
            vals.update(is_free=True, free_reason=free_reason,
                        price_usd=0.0, price_local=0.0, fx_rate=1.0,
                        currency_id=(account.billing_currency_id.id
                                     if account and account.billing_currency_id else False))
            return vals

        # Volume tier
        mtd = self._month_to_date_qty(account, country, category, event_date)
        rate = card.resolve_rate(country, category, mtd)
        if not rate:
            _logger.warning('No rate for card=%s country=%s category=%s',
                            card.name, country.code or 'GLOBAL', category)
            vals.update(price_usd=0.0, price_local=0.0, fx_rate=1.0)
            return vals

        price_usd = unit_qty * rate.price_usd
        currency = (account.billing_currency_id if account and account.billing_currency_id
                    else self.env.ref('base.USD', raise_if_not_found=False))
        fx = 1.0
        if currency and currency.name != 'USD':
            fx = self.env['whatsapp.fx.rate'].rate_for(currency, event_date)

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

    # ---- Ingestion helpers (called from inherit hooks) ----
    @api.model
    def _create_from_message(self, message):
        """Ingest a whatsapp.message once its pricing_category is known."""
        if not message.pricing_category:
            return self.browse()
        exists = self.search([('source_model', '=', 'whatsapp.message'),
                              ('source_id', '=', message.id)], limit=1)
        if exists:
            return exists
        # Map Meta's category strings to our enum
        cat_map = {
            'marketing':                     'marketing',
            'utility':                       'utility',
            'authentication':                'authentication',
            'authentication_international':  'auth_international',
            'service':                       'service',
            # legacy conversation-based
            'business_initiated':            'marketing',
            'user_initiated':                'service',
            'referral_conversion':           'service',
        }
        category = cat_map.get((message.pricing_category or '').lower())
        if not category:
            _logger.info('Unknown pricing_category %r on message %s',
                         message.pricing_category, message.id)
            return self.browse()
        return self.create({
            'event_date': message.status_timestamp or message.message_timestamp
                          or fields.Datetime.now(),
            'account_id': (message.account_id.id if 'account_id' in message._fields
                           and message.account_id else False),
            'partner_id': (message.partner_id.id if 'partner_id' in message._fields
                           and message.partner_id else False),
            'wa_id': message.wa_id,
            'category': category,
            'unit': 'message',
            'unit_qty': 1.0,
            'source_model': 'whatsapp.message',
            'source_id': message.id,
            'message_id': message.id,
        })

    @api.model
    def _create_from_call(self, call):
        if not call.duration or call.duration <= 0:
            return self.browse()
        exists = self.search([('source_model', '=', 'whatsapp.call.log'),
                              ('source_id', '=', call.id)], limit=1)
        if exists:
            return exists
        # Destination = the non-business leg
        wa_id = (call.to_number if call.call_direction == 'outbound'
                 else call.from_number)
        minutes = round((call.duration or 0) / 60.0, 4)
        return self.create({
            'event_date': (call.end_timestamp or call.call_timestamp
                           or fields.Datetime.now()),
            'account_id': call.account_id.id if call.account_id else False,
            'partner_id': call.partner_id.id if call.partner_id else False,
            'wa_id': wa_id,
            'category': 'call_minute',
            'unit': 'minute',
            'unit_qty': minutes,
            'source_model': 'whatsapp.call.log',
            'source_id': call.id,
        })

    @api.model
    def record_mba_interaction(self, account, wa_id, tokens, event_date=None,
                               partner=None, source_ref=None):
        """Public API for the (future) MBA integration to log token spend."""
        return self.create({
            'event_date': event_date or fields.Datetime.now(),
            'account_id': account.id if account else False,
            'partner_id': partner.id if partner else False,
            'wa_id': wa_id,
            'category': 'mba_token',
            'unit': 'kilotoken',
            'unit_qty': tokens / 1000.0,
            'source_model': source_ref and source_ref._name,
            'source_id': source_ref and source_ref.id,
        })
