# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import UserError


WA_CATEGORY_SELECTION = [
    ('marketing',          'Marketing'),
    ('utility',            'Utility'),
    ('authentication',     'Authentication'),
    ('auth_international', 'Authentication-International'),
    ('service',            'Service'),
]


class WhatsappCostSimulation(models.TransientModel):
    _name = 'whatsapp.cost.simulation'
    _description = 'WhatsApp cost simulation wizard'

    account_id = fields.Many2one('comm.whatsapp.account')
    audience_domain = fields.Char(default="[]",
        help='Odoo domain on res.partner selecting the target audience.')
    manual_recipient_count = fields.Integer(default=0)
    manual_country_id = fields.Many2one('res.country',
        help='When using manual recipient count, assume this country.')
    category = fields.Selection(WA_CATEGORY_SELECTION,
                                required=True, default='marketing')
    expected_reply_rate = fields.Float(default=0.0)
    mba_handled_pct = fields.Float(default=0.0)
    avg_tokens_per_interaction = fields.Integer(default=22000)
    avg_call_minutes_per_recipient = fields.Float(default=0.0)

    rate_card_ids = fields.Many2many('comm.billing.rate.card',
        string='Compare against rate cards',
        domain=[('channel', '=', 'whatsapp')])

    display_currency_id = fields.Many2one('res.currency', string='Display in',
        default=lambda self: self.env.company.currency_id)
    display_fx_rate = fields.Float(string='USD → display FX', digits=(12, 6))

    result_json = fields.Text(readonly=True)
    result_summary = fields.Html(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        cards = self.env['comm.billing.rate.card'].search([
            ('channel', '=', 'whatsapp'),
            ('active', '=', True),
        ], order='effective_from')
        vals['rate_card_ids'] = [(6, 0, cards.ids)]
        currency = self.env.company.currency_id
        vals.setdefault('display_currency_id', currency.id if currency else False)
        fx, _ = self.env['comm.billing.event']._resolve_fx(
            'Meta', fields.Date.today(), currency_hint=currency)
        vals.setdefault('display_fx_rate', fx or 1.0)
        return vals

    def _audience_country_split(self):
        if self.audience_domain and self.audience_domain.strip() not in ('', '[]'):
            try:
                domain = eval(self.audience_domain, {'__builtins__': {}}, {})
            except Exception as e:
                raise UserError(f'Invalid audience_domain: {e}')
            partners = self.env['res.partner'].search(domain)
            split = defaultdict(int)
            for p in partners:
                country = p.country_id or self.manual_country_id
                split[country] += 1
            return dict(split)
        if self.manual_recipient_count > 0 and self.manual_country_id:
            return {self.manual_country_id: self.manual_recipient_count}
        raise UserError(
            'Provide either an audience_domain or manual_recipient_count + country.')

    def _project(self, card, country_split):
        result = {
            'card_id': card.id, 'card_name': card.name,
            'billing_model': card.billing_model,
            'lines': [], 'total_usd': 0.0,
        }
        for country, recipients in country_split.items():
            rate = card.resolve_rate(country=country, category=self.category)
            price = (rate.price_usd if rate else 0.0) * recipients
            result['lines'].append({
                'country': country.code or 'GLOBAL',
                'category': self.category, 'qty': recipients,
                'unit_price': rate.price_usd if rate else 0.0,
                'total': price,
            })
            result['total_usd'] += price

            if card.billing_model in ('hybrid_2026', 'hybrid_service_paid'):
                replies = recipients * (self.expected_reply_rate or 0)
                mba_replies = replies * (self.mba_handled_pct or 0)
                if mba_replies > 0:
                    tokens = mba_replies * (self.avg_tokens_per_interaction or 0)
                    rate = card.resolve_rate(category='mba_token')
                    kt = tokens / 1000.0
                    mba_price = (rate.price_usd if rate else 0.0) * kt
                    result['lines'].append({
                        'country': 'GLOBAL', 'category': 'mba_token',
                        'qty': kt,
                        'unit_price': rate.price_usd if rate else 0.0,
                        'total': mba_price,
                    })
                    result['total_usd'] += mba_price

                if card.billing_model == 'hybrid_service_paid':
                    paid_service = replies - mba_replies
                    if paid_service > 0:
                        rate = card.resolve_rate(country=country, category='service')
                        svc_price = (rate.price_usd if rate else 0.0) * paid_service
                        result['lines'].append({
                            'country': country.code or 'GLOBAL',
                            'category': 'service', 'qty': paid_service,
                            'unit_price': rate.price_usd if rate else 0.0,
                            'total': svc_price,
                        })
                        result['total_usd'] += svc_price
        return result

    def action_run(self):
        self.ensure_one()
        country_split = self._audience_country_split()
        cards = self.rate_card_ids or self.env['comm.billing.rate.card'].search([
            ('channel', '=', 'whatsapp'), ('active', '=', True),
        ], order='effective_from')
        projections = [self._project(card, country_split) for card in cards]
        self.result_json = json.dumps(projections, indent=2, default=str)
        self.result_summary = self._render(projections)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _render(self, projections):
        fx = self.display_fx_rate or 1.0
        sym = self.display_currency_id.symbol or self.display_currency_id.name or ''
        html = ['<div class="o_whatsapp_cost_summary">']
        for p in projections:
            html.append(f'<h4>{p["card_name"]} <small>({p["billing_model"]})</small></h4>')
            html.append('<table class="table table-sm"><thead><tr>'
                        '<th>Country</th><th>Category</th>'
                        '<th class="text-end">Qty</th>'
                        f'<th class="text-end">Total ({sym})</th>'
                        '<th class="text-end">Total ($)</th></tr></thead><tbody>')
            for line in p['lines']:
                html.append(f'<tr><td>{line["country"]}</td>'
                            f'<td>{line["category"]}</td>'
                            f'<td class="text-end">{line["qty"]:.2f}</td>'
                            f'<td class="text-end">{line["total"] * fx:,.2f}</td>'
                            f'<td class="text-end">{line["total"]:.4f}</td></tr>')
            html.append(f'<tr><td colspan="3"><b>Total</b></td>'
                        f'<td class="text-end"><b>{sym} {p["total_usd"] * fx:,.2f}</b></td>'
                        f'<td class="text-end">${p["total_usd"]:.4f}</td></tr>')
            html.append('</tbody></table>')
        html.append('</div>')
        return ''.join(html)
