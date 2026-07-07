# -*- coding: utf-8 -*-
"""What-if projection for a campaign before pressing Run now.

Improvements over v1:
- Per-partner country resolution: partner.country_id → MSISDN prefix →
  fallback ZA. Rates looked up per (country, channel).
- Drop-off model: bot graph split into GUARANTEED steps (before first
  menu/input/wait) and CONDITIONAL steps (past a user-input gate).
  Conditional steps scaled by engagement_rate_pct — default 30% mirrors
  typical WhatsApp campaign engagement.
- Cost range shown: min (guaranteed only) → realistic (guaranteed +
  conditional × engagement) → best (100% engagement).
- Send preview: renders the entry step against a chosen partner on each
  channel in priority order — shows what recipient #1 will actually see.
"""
import logging
import phonenumbers
from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


BUDGET_STATUS_SELECTION = [
    ('ok',       'OK'),
    ('warn',     'Above soft threshold'),
    ('exceeded', 'Exceeds cap'),
    ('none',     'No cap set'),
]


class CommCampaignSimulation(models.TransientModel):
    _name = 'comm.campaign.simulation'
    _description = 'Campaign what-if simulator'

    campaign_id = fields.Many2one('comm.campaign', required=True, readonly=True)

    # Inputs
    engagement_rate_pct = fields.Integer(
        string='Engagement rate (%)',
        default=30,
        help='Fraction of recipients expected to interact past the first '
             'menu/input. Cost = guaranteed + conditional × this.')
    preview_partner_id = fields.Many2one('res.partner',
        string='Preview recipient',
        help='Partner used for the Send preview panel. Auto-picks the first '
             'reachable audience member if empty.')

    # Audience
    total_audience = fields.Integer(readonly=True)
    reachable_count = fields.Integer(readonly=True)
    opted_out_count = fields.Integer(readonly=True)
    unreachable_count = fields.Integer(readonly=True)

    # Bot analysis
    guaranteed_step_count = fields.Integer(readonly=True,
        help='Outbound steps before the first user-input gate.')
    conditional_step_count = fields.Integer(readonly=True,
        help='Outbound steps reachable only if the user engages.')
    llm_step_count = fields.Integer(readonly=True)
    llm_projected_tokens_per_conversation = fields.Integer(readonly=True)

    # Costs — three scenarios
    cost_min_usd = fields.Float(readonly=True, digits=(12, 4),
        help='Guaranteed steps only (0% engagement past first gate).')
    cost_realistic_usd = fields.Float(readonly=True, digits=(12, 4),
        help='At the configured engagement_rate_pct.')
    cost_max_usd = fields.Float(readonly=True, digits=(12, 4),
        help='100% engagement (upper bound).')

    cost_min_local = fields.Float(readonly=True, digits=(12, 2))
    cost_realistic_local = fields.Float(readonly=True, digits=(12, 2))
    cost_max_local = fields.Float(readonly=True, digits=(12, 2))
    display_currency_id = fields.Many2one('res.currency', readonly=True)

    # Budget (against realistic)
    budget_cap_local = fields.Float(readonly=True, digits=(12, 2))
    budget_status = fields.Selection(BUDGET_STATUS_SELECTION, readonly=True)
    budget_utilization_pct = fields.Float(readonly=True, digits=(6, 2))

    # ETA
    eta_minutes = fields.Integer(readonly=True)
    eta_display = fields.Char(readonly=True)

    # Result html
    channel_projection_html = fields.Html(readonly=True)
    variant_projection_html = fields.Html(readonly=True)
    send_preview_html = fields.Html(readonly=True)
    summary_html = fields.Html(readonly=True)
    assumptions_html = fields.Html(readonly=True)

    # ---------- Public entry ----------
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        campaign_id = self.env.context.get('active_id') \
            or self.env.context.get('default_campaign_id')
        if campaign_id:
            vals['campaign_id'] = campaign_id
        return vals

    def action_run(self):
        for wiz in self:
            wiz._simulate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ---------- Simulation ----------
    def _simulate(self):
        self.ensure_one()
        campaign = self.campaign_id
        if not campaign or not campaign.bot_id:
            raise UserError('Campaign has no bot to project.')

        # 1. Resolve audience
        partners = self._resolve_audience(campaign)
        total = len(partners)

        # 2. Analyse bot graph
        analysis = self._analyse_bot(campaign.bot_id)

        # 3. Per-partner channel projection: (country_id, channel_id) → [partner_ids]
        buckets = defaultdict(list)
        opted_out_ids = []
        unreachable_ids = []

        Pref = self.env['comm.partner.communication.preference']
        Registry = self.env['comm.chatbot.registry']
        priority = campaign.channel_priority_ids.sorted('sequence')

        first_reachable = None
        for partner in partners:
            assigned = self._pick_channel(partner, priority, Registry, Pref,
                                          campaign.purpose)
            if assigned == 'opted_out':
                opted_out_ids.append(partner.id)
                continue
            if assigned is None:
                unreachable_ids.append(partner.id)
                continue
            country = self._country_for_partner(partner)
            buckets[(country.id if country else 0, assigned.id)].append(partner.id)
            if first_reachable is None:
                first_reachable = partner

        reachable_count = sum(len(v) for v in buckets.values())

        # 4. Cost projection per (country, channel) bucket
        currency = campaign.budget_currency_id or self.env.company.currency_id
        er = max(0, min(self.engagement_rate_pct or 0, 100)) / 100.0

        min_usd = real_usd = max_usd = 0.0
        rows = []

        for (country_id, channel_id), partner_ids in buckets.items():
            channel = self.env['comm.channel'].browse(channel_id)
            country = self.env['res.country'].browse(country_id) if country_id else False
            per_min, per_real, per_max = self._per_recipient(
                channel, country, analysis, er)
            n = len(partner_ids)
            row_min = per_min * n
            row_real = per_real * n
            row_max = per_max * n
            min_usd += row_min
            real_usd += row_real
            max_usd += row_max
            rows.append({
                'channel': channel.name,
                'country': country.code if country else 'GLOBAL',
                'recipients': n,
                'per_recipient_realistic': per_real,
                'realistic_bucket': row_real,
                'min_bucket': row_min,
                'max_bucket': row_max,
            })

        # 5. FX to local
        fx, _ = self.env['comm.billing.event']._resolve_fx(
            None, fields.Date.today(), currency_hint=currency)
        fx = fx or 1.0

        # 6. Budget against realistic
        cap = campaign.budget_cap_local or 0.0
        realistic_local = real_usd * fx
        if not cap:
            status, util_pct = 'none', 0.0
        else:
            util_pct = (realistic_local / cap) * 100
            if util_pct >= 100:
                status = 'exceeded'
            elif util_pct >= (campaign.budget_soft_threshold_pct or 80):
                status = 'warn'
            else:
                status = 'ok'

        # 7. ETA
        throttle = max(campaign.throttle_per_minute or 60, 1)
        eta_min = int((reachable_count + throttle - 1) / throttle)

        # 8. Variant split
        variant_html = self._project_variants(campaign, reachable_count)

        # 9. Send preview
        preview_partner = self.preview_partner_id or first_reachable
        send_preview = self._render_send_preview(preview_partner, priority)

        # 10. Write result
        self.write({
            'total_audience': total,
            'reachable_count': reachable_count,
            'opted_out_count': len(opted_out_ids),
            'unreachable_count': len(unreachable_ids),
            'guaranteed_step_count': analysis['guaranteed_billable'],
            'conditional_step_count': analysis['conditional_billable'],
            'llm_step_count': (analysis['llm_steps_guaranteed'] +
                               analysis['llm_steps_conditional']),
            'llm_projected_tokens_per_conversation':
                analysis['llm_tokens_per_convo'],
            'cost_min_usd': min_usd,
            'cost_realistic_usd': real_usd,
            'cost_max_usd': max_usd,
            'cost_min_local': min_usd * fx,
            'cost_realistic_local': realistic_local,
            'cost_max_local': max_usd * fx,
            'display_currency_id': currency.id if currency else False,
            'budget_cap_local': cap,
            'budget_status': status,
            'budget_utilization_pct': util_pct,
            'eta_minutes': eta_min,
            'eta_display': self._format_eta(eta_min),
            'preview_partner_id':
                preview_partner.id if preview_partner else False,
            'channel_projection_html':
                self._render_channels(rows, currency, fx),
            'variant_projection_html': variant_html,
            'send_preview_html': send_preview,
            'summary_html': self._render_summary(
                total, reachable_count, min_usd * fx, realistic_local,
                max_usd * fx, cap, util_pct, status,
                self._format_eta(eta_min), currency),
            'assumptions_html': self._render_assumptions(),
        })

    # ---------- Audience resolution ----------
    def _resolve_audience(self, campaign):
        if campaign.audience_mode == 'static' and campaign.snapshot_ids:
            return campaign.snapshot_ids.mapped('partner_id')
        try:
            domain = eval(campaign.audience_domain or '[]',
                          {'__builtins__': {}}, {})
        except Exception as e:
            raise UserError(f'Invalid audience_domain: {e}')
        return self.env['res.partner'].search(domain)

    def _pick_channel(self, partner, priority, Registry, Pref, purpose):
        for channel in priority:
            adapter_cls = Registry.get_adapter_for_channel(channel)
            if not adapter_cls:
                continue
            try:
                if not adapter_cls().can_reach(self.env, partner):
                    continue
            except Exception:
                continue
            if not Pref.is_opted_in(partner, channel, purpose):
                return 'opted_out'
            return channel
        return None

    # ---------- Country resolution ----------
    def _country_for_partner(self, partner):
        if partner.country_id:
            return partner.country_id
        for candidate in (partner.mobile, partner.phone):
            if not candidate:
                continue
            try:
                num = phonenumbers.parse('+' + candidate.lstrip('+'))
                code = phonenumbers.region_code_for_number(num)
                if code:
                    return self.env['res.country'].search(
                        [('code', '=', code)], limit=1)
            except Exception:
                continue
        return self.env.ref('base.za', raise_if_not_found=False)

    # ---------- Bot graph analysis ----------
    def _analyse_bot(self, bot):
        """Split reachable outbound steps into GUARANTEED (fire on 100% of
        recipients) and CONDITIONAL (fire only if user engages)."""
        outbound_kinds = {'message', 'menu', 'input', 'handoff',
                          'channel_switch', 'llm'}
        gate_kinds = {'menu', 'input', 'wait'}
        counts = {
            'guaranteed_billable': 0,
            'conditional_billable': 0,
            'llm_steps_guaranteed': 0,
            'llm_steps_conditional': 0,
            'llm_tokens_per_convo': 0,
        }

        guaranteed_visited = set()
        conditional_frontier = []

        def guaranteed_visit(step):
            if not step or step.id in guaranteed_visited:
                return
            guaranteed_visited.add(step.id)
            if step.kind in outbound_kinds:
                counts['guaranteed_billable'] += 1
                if step.kind == 'llm':
                    counts['llm_steps_guaranteed'] += 1
                    out = int((step.llm_max_tokens or 1024) * 0.6)
                    counts['llm_tokens_per_convo'] += 3000 + out
            if step.kind in gate_kinds:
                # Everything past a gate is conditional
                for opt in step.option_ids:
                    if opt.next_step_id:
                        conditional_frontier.append(opt.next_step_id)
                if step.next_step_id:
                    conditional_frontier.append(step.next_step_id)
                return
            if step.next_step_id:
                guaranteed_visit(step.next_step_id)
            for opt in step.option_ids:
                if opt.next_step_id:
                    guaranteed_visit(opt.next_step_id)
            if step.jump_target_step_id:
                guaranteed_visit(step.jump_target_step_id)

        conditional_visited = set()

        def conditional_visit(step):
            if (not step or step.id in conditional_visited
                    or step.id in guaranteed_visited):
                return
            conditional_visited.add(step.id)
            if step.kind in outbound_kinds:
                counts['conditional_billable'] += 1
                if step.kind == 'llm':
                    counts['llm_steps_conditional'] += 1
                    out = int((step.llm_max_tokens or 1024) * 0.6)
                    # Attribute to per-convo total; simulator will scale by
                    # engagement rate when converting to cost
                    counts['llm_tokens_per_convo'] += 3000 + out
            if step.next_step_id:
                conditional_visit(step.next_step_id)
            for opt in step.option_ids:
                if opt.next_step_id:
                    conditional_visit(opt.next_step_id)
            for opt in step.llm_decision_option_ids:
                conditional_visit(opt)
            if step.jump_target_step_id:
                conditional_visit(step.jump_target_step_id)
            if step.llm_fallback_step_id:
                conditional_visit(step.llm_fallback_step_id)

        guaranteed_visit(bot.entry_step_id)
        for s in conditional_frontier:
            conditional_visit(s)

        return counts

    # ---------- Cost per recipient ----------
    def _per_recipient(self, channel, country, analysis, engagement_rate):
        """Return (min_usd, realistic_usd, max_usd) per recipient."""
        today = fields.Date.today()
        card = self.env['comm.billing.rate.card'].active_on(channel.code, today)
        if not card:
            return 0.0, 0.0, 0.0

        cat_map = {
            'whatsapp': 'marketing',
            'sms':      'sms_outbound_domestic',
            'ussd':     'ussd_session',
            'voice':    'voice_outbound_local_mobile',
        }
        category = cat_map.get(channel.code)
        if not category:
            return 0.0, 0.0, 0.0

        rate_row = card.resolve_rate(country=country, category=category)
        if not rate_row:
            rate_row = card.resolve_rate(country=None, category=category)
        per_step_usd = rate_row.price_usd if rate_row else 0.0

        # Message costs
        message_min = per_step_usd * analysis['guaranteed_billable']
        message_real = message_min + per_step_usd * analysis['conditional_billable'] * engagement_rate
        message_max = per_step_usd * (analysis['guaranteed_billable'] +
                                       analysis['conditional_billable'])

        # LLM cost — token rate lookup (use WA hybrid card for mba_token)
        token_price = self._resolve_token_price()
        llm_kt = analysis['llm_tokens_per_convo'] / 1000.0
        llm_guaranteed_kt = self._kt_for_guaranteed(analysis)
        llm_conditional_kt = llm_kt - llm_guaranteed_kt

        llm_min = token_price * llm_guaranteed_kt
        llm_real = llm_min + token_price * llm_conditional_kt * engagement_rate
        llm_max = token_price * llm_kt

        return (message_min + llm_min,
                message_real + llm_real,
                message_max + llm_max)

    def _kt_for_guaranteed(self, analysis):
        """LLM kilotokens attributable to guaranteed LLM steps."""
        if not analysis['llm_step_count'] if 'llm_step_count' in analysis else False:
            pass
        total_llm = (analysis['llm_steps_guaranteed'] +
                     analysis['llm_steps_conditional'])
        if total_llm == 0:
            return 0.0
        share = analysis['llm_steps_guaranteed'] / total_llm
        return (analysis['llm_tokens_per_convo'] / 1000.0) * share

    def _resolve_token_price(self):
        card = self.env['comm.billing.rate.card'].search([
            ('channel', '=', 'whatsapp'),
            ('billing_model', 'in', ('hybrid_2026', 'hybrid_service_paid')),
        ], limit=1, order='effective_from desc')
        if not card:
            return 0.002
        rate = card.resolve_rate(country=None, category='mba_token')
        return rate.price_usd if rate else 0.002

    # ---------- Variant projection ----------
    def _project_variants(self, campaign, reachable):
        if not campaign.variant_ids:
            return '<p><em>No A/B variants defined.</em></p>'
        total_weight = sum(v.weight for v in campaign.variant_ids)
        if total_weight == 0:
            return '<p>All variants have zero weight — check assignment.</p>'
        html = ['<table class="table table-sm">',
                '<thead><tr><th>Variant</th><th>Bot</th>'
                '<th class="text-end">Weight</th>'
                '<th class="text-end">Projected recipients</th>'
                '</tr></thead><tbody>']
        for v in campaign.variant_ids:
            share = (v.weight / total_weight) if total_weight else 0
            html.append(f'<tr><td>{v.name}</td>'
                        f'<td>{v.bot_id.name if v.bot_id else "—"}</td>'
                        f'<td class="text-end">{v.weight}</td>'
                        f'<td class="text-end">{int(reachable * share)}</td>'
                        f'</tr>')
        html.append('</tbody></table>')
        return ''.join(html)

    # ---------- Send preview ----------
    def _render_send_preview(self, partner, priority_channels):
        if not partner:
            return '<p><em>No reachable recipient to preview.</em></p>'
        bot = self.campaign_id.bot_id
        if not bot.entry_step_id:
            return '<p>Bot has no entry step.</p>'

        conversation = self.env['comm.conversation'].create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id':
                priority_channels[:1].id if priority_channels else False,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview__',
        })
        renderer = self.env['comm.chatbot.renderer']

        html = [f'<div class="o_campaign_send_preview">'
                f'<p><em>Previewing bot entry step for '
                f'<b>{partner.name}</b>.</em></p>']

        try:
            for channel in priority_channels.sorted('sequence'):
                html.append(f'<h5 class="mt-3">📱 {channel.name} '
                            f'<small class="text-muted">({channel.code})</small></h5>')
                conversation.primary_channel_id = channel
                try:
                    payload = renderer.render(bot.entry_step_id, conversation)
                    html.append('<div class="card p-2 mb-2">')
                    body = payload.get('body') or '<em>(empty)</em>'
                    html.append('<div><strong>Body:</strong></div>'
                                f'<pre style="white-space: pre-wrap;">{body}</pre>')
                    options = payload.get('options') or []
                    if options:
                        rendered_as = ('inline buttons' if channel.supports_buttons
                                       and len(options) <= (channel.max_buttons or 0)
                                       else 'list' if channel.supports_lists
                                       else 'numbered text (embedded in body)')
                        html.append(f'<div class="mt-1"><strong>Options</strong> '
                                    f'({len(options)}, rendered as {rendered_as}):</div>'
                                    '<ul>')
                        for i, opt in enumerate(options):
                            html.append(f'<li>{opt.get("label", "")}</li>')
                        html.append('</ul>')
                    media = payload.get('media') or []
                    if media:
                        html.append(f'<div class="mt-1"><strong>Media:</strong> '
                                    f'{len(media)} attachment(s)</div>')
                    html.append('</div>')
                except Exception as e:
                    html.append(f'<div class="alert alert-danger">'
                                f'Render error: {e}</div>')
        finally:
            conversation.sudo().unlink()

        html.append('</div>')
        return ''.join(html)

    # ---------- HTML renderers ----------
    def _render_channels(self, rows, currency, fx):
        if not rows:
            return '<p><em>No recipients projected on any channel.</em></p>'
        sym = currency.symbol or currency.name or ''
        html = ['<table class="table table-sm">',
                '<thead><tr>'
                '<th>Channel</th><th>Country</th>'
                '<th class="text-end">Recipients</th>'
                '<th class="text-end">Per-recipient (USD, realistic)</th>'
                f'<th class="text-end">Realistic ({sym})</th>'
                f'<th class="text-end">Min ({sym})</th>'
                f'<th class="text-end">Max ({sym})</th>'
                '</tr></thead><tbody>']
        for r in rows:
            html.append(f'<tr>'
                        f'<td>{r["channel"]}</td>'
                        f'<td>{r["country"]}</td>'
                        f'<td class="text-end">{r["recipients"]}</td>'
                        f'<td class="text-end">${r["per_recipient_realistic"]:.4f}</td>'
                        f'<td class="text-end">{r["realistic_bucket"] * fx:,.2f}</td>'
                        f'<td class="text-end text-muted">{r["min_bucket"] * fx:,.2f}</td>'
                        f'<td class="text-end text-muted">{r["max_bucket"] * fx:,.2f}</td>'
                        '</tr>')
        html.append('</tbody></table>')
        return ''.join(html)

    def _render_summary(self, total, reachable, min_local, real_local, max_local,
                        cap, util_pct, status, eta_display, currency):
        sym = (currency and currency.symbol) or (currency and currency.name) or ''
        status_colour = {
            'ok': 'success', 'warn': 'warning',
            'exceeded': 'danger', 'none': 'secondary',
        }[status]
        cap_line = ''
        if status != 'none':
            cap_line = (f'<div>Budget: {sym} {real_local:,.2f} / '
                        f'{sym} {cap:,.2f} '
                        f'(<b>{util_pct:.1f}%</b>) — '
                        f'<span class="badge text-bg-{status_colour}">{status}</span></div>')
        return (
            f'<div class="o_campaign_sim_summary">'
            f'<div><b>Audience:</b> {total} • <b>Reachable:</b> {reachable}</div>'
            f'<div><b>Projected cost (realistic):</b> {sym} {real_local:,.2f} '
            f'<span class="text-muted">'
            f'(range: {sym} {min_local:,.2f} – {sym} {max_local:,.2f})'
            f'</span></div>'
            f'{cap_line}'
            f'<div><b>ETA to complete:</b> {eta_display}</div>'
            f'</div>'
        )

    def _render_assumptions(self):
        return (
            '<ul>'
            '<li><b>Guaranteed steps</b> fire on 100% of reachable recipients — '
            'they\'re outbounds reachable before the first menu/input gate.</li>'
            '<li><b>Conditional steps</b> fire only when recipients engage past '
            'the first gate; scaled by the engagement rate you set '
            '(default 30% mirrors typical WA campaign response).</li>'
            '<li>Cost range: <b>min</b> = guaranteed only, <b>realistic</b> = '
            'guaranteed + conditional × engagement, <b>max</b> = 100% engagement.</li>'
            '<li>Country resolution: partner.country_id → MSISDN prefix via '
            'phonenumbers → ZA fallback. Rates looked up per country.</li>'
            '<li>LLM tokens: ~3,000 input (system prompt + history) plus '
            '60% of max_tokens output per LLM step. Fallback-model retries '
            'add ~10% headroom.</li>'
            '<li>Quiet hours shift <em>when</em>, not <em>whether</em> — the '
            'ETA doesn\'t model deferrals.</li>'
            '</ul>'
        )

    def _format_eta(self, minutes):
        if minutes < 1:
            return '< 1 minute'
        if minutes < 60:
            return f'{minutes} min'
        hours = minutes // 60
        rem = minutes % 60
        if hours < 24:
            return f'{hours}h {rem}m' if rem else f'{hours}h'
        days = hours // 24
        rh = hours % 24
        return f'{days}d {rh}h' if rh else f'{days}d'
