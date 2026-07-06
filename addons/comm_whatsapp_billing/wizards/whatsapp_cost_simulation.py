# -*- coding: utf-8 -*-
import json
from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import UserError

from ..models.whatsapp_rate import CATEGORY_SELECTION


class WhatsappCostSimulation(models.TransientModel):
    _name = 'whatsapp.cost.simulation'
    _description = 'WhatsApp cost simulation wizard'

    name = fields.Char(default='Cost simulation')
    account_id = fields.Many2one('comm.whatsapp.account')
    audience_domain = fields.Char(default="[]",
        help='Odoo domain on res.partner selecting the target audience. '
             'Leave as [] to enter a manual recipient count instead.')
    manual_recipient_count = fields.Integer(default=0)
    manual_country_id = fields.Many2one('res.country',
        help='When using manual recipient count, assume all recipients are in this country.')
    category = fields.Selection(CATEGORY_SELECTION,
                                required=True, default='marketing')
    expected_reply_rate = fields.Float(default=0.0,
        help='Fraction of recipients who reply (0-1). Used for MBA token projection.')
    mba_handled_pct = fields.Float(default=0.0,
        help='Fraction of replies handled by Meta Business Agent (0-1).')
    avg_tokens_per_interaction = fields.Integer(default=22000)
    avg_call_minutes_per_recipient = fields.Float(default=0.0)

    rate_card_ids = fields.Many2many('whatsapp.rate.card',
        string='Compare against rate cards',
        help='Pick one or more rate cards for side-by-side comparison. '
             'Defaults to the current + next future cards.')

    result_json = fields.Text(readonly=True)
    result_summary = fields.Html(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        # Preselect the currently active card and any future ones
        cards = self.env['whatsapp.rate.card'].search([
            ('active', '=', True),
        ], order='effective_from')
        vals['rate_card_ids'] = [(6, 0, cards.ids)]
        return vals

    def _audience_country_split(self):
        """Return dict {res.country: recipient_count} for the audience."""
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

    def _project_for_card(self, card, country_split):
        """Return dict with per-category cost breakdown under this card."""
        total_recipients = sum(country_split.values())
        result = {
            'card_id': card.id,
            'card_name': card.name,
            'billing_model': card.billing_model,
            'lines': [],
            'total_usd': 0.0,
        }

        for country, recipients in country_split.items():
            # 1) Template send (the chosen category)
            rate = card.resolve_rate(country, self.category, 0)
            price = (rate.price_usd if rate else 0.0) * recipients
            result['lines'].append({
                'country': country.code or 'GLOBAL',
                'category': self.category,
                'qty': recipients,
                'unit_price': rate.price_usd if rate else 0.0,
                'total': price,
            })
            result['total_usd'] += price

            # 2) MBA tokens (only if hybrid card)
            if card.billing_model in ('hybrid_2026', 'hybrid_service_paid'):
                replies = recipients * (self.expected_reply_rate or 0)
                mba_replies = replies * (self.mba_handled_pct or 0)
                if mba_replies > 0:
                    tokens = mba_replies * (self.avg_tokens_per_interaction or 0)
                    rate = card.resolve_rate(None, 'mba_token', 0)
                    kt = tokens / 1000.0
                    mba_price = (rate.price_usd if rate else 0.0) * kt
                    result['lines'].append({
                        'country': 'GLOBAL',
                        'category': 'mba_token',
                        'qty': kt,
                        'unit_price': rate.price_usd if rate else 0.0,
                        'total': mba_price,
                    })
                    result['total_usd'] += mba_price

                # Post-Oct 2026 non-MBA replies fall to paid service
                if card.billing_model == 'hybrid_service_paid':
                    paid_service = replies - mba_replies
                    if paid_service > 0:
                        rate = card.resolve_rate(country, 'service', 0)
                        svc_price = (rate.price_usd if rate else 0.0) * paid_service
                        result['lines'].append({
                            'country': country.code or 'GLOBAL',
                            'category': 'service',
                            'qty': paid_service,
                            'unit_price': rate.price_usd if rate else 0.0,
                            'total': svc_price,
                        })
                        result['total_usd'] += svc_price

            # 3) Call minutes
            if self.avg_call_minutes_per_recipient > 0:
                minutes = recipients * self.avg_call_minutes_per_recipient
                rate = card.resolve_rate(country, 'call_minute', 0)
                if rate:
                    call_price = rate.price_usd * minutes
                    result['lines'].append({
                        'country': country.code or 'GLOBAL',
                        'category': 'call_minute',
                        'qty': minutes,
                        'unit_price': rate.price_usd,
                        'total': call_price,
                    })
                    result['total_usd'] += call_price

        return result

    def action_run(self):
        self.ensure_one()
        country_split = self._audience_country_split()
        cards = self.rate_card_ids or self.env['whatsapp.rate.card'].search([
            ('active', '=', True),
        ], order='effective_from')

        projections = []
        for card in cards:
            projections.append(self._project_for_card(card, country_split))

        self.result_json = json.dumps(projections, indent=2, default=str)
        self.result_summary = self._render_summary(projections)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _render_summary(self, projections):
        html = ['<div class="o_whatsapp_cost_summary">']
        for p in projections:
            html.append(f'<h4>{p["card_name"]} <small>({p["billing_model"]})</small></h4>')
            html.append('<table class="table table-sm"><thead><tr>'
                        '<th>Country</th><th>Category</th>'
                        '<th class="text-end">Qty</th>'
                        '<th class="text-end">Unit ($)</th>'
                        '<th class="text-end">Total ($)</th></tr></thead><tbody>')
            for line in p['lines']:
                html.append(f'<tr><td>{line["country"]}</td>'
                            f'<td>{line["category"]}</td>'
                            f'<td class="text-end">{line["qty"]:.2f}</td>'
                            f'<td class="text-end">{line["unit_price"]:.6f}</td>'
                            f'<td class="text-end">{line["total"]:.4f}</td></tr>')
            html.append(f'<tr><td colspan="4"><b>Total</b></td>'
                        f'<td class="text-end"><b>${p["total_usd"]:.4f}</b></td></tr>')
            html.append('</tbody></table>')
        html.append('</div>')
        return ''.join(html)
