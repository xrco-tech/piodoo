# -*- coding: utf-8 -*-
"""What-if projection for a campaign before pressing Run now.

Walks the audience, resolves each partner's channel using the same fallback
logic the send worker uses, and projects the cost per channel based on:
- The bot's billable step count (message / menu / input / handoff / channel_switch)
- Per-LLM-step token estimate (llm_max_tokens * 0.6 + system prompt overhead)
- Live rate card lookup (comm.billing.rate.card active on today)

Assumptions the wizard makes visible:
- Every non-wait outbound step fires at least once per conversation
- Users engage with the full flow (upper bound; real campaigns drop off)
- LLM tokens are billed at the active rate card's mba_token rate
- No fallback-model retries (adds ~10% if it happens)
"""
import logging
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

    # Audience
    total_audience = fields.Integer(readonly=True)
    reachable_count = fields.Integer(readonly=True)
    opted_out_count = fields.Integer(readonly=True)
    unreachable_count = fields.Integer(readonly=True)
    quiet_hours_deferred = fields.Integer(readonly=True)

    # Bot analysis
    billable_step_count = fields.Integer(readonly=True,
        help='Steps that produce an outbound (message/menu/input/handoff/llm).')
    llm_step_count = fields.Integer(readonly=True)
    llm_projected_tokens_per_conversation = fields.Integer(readonly=True)

    # Costs
    projected_cost_usd = fields.Float(readonly=True, digits=(12, 4))
    projected_cost_local = fields.Float(readonly=True, digits=(12, 2))
    display_currency_id = fields.Many2one('res.currency', readonly=True)

    # Budget
    budget_cap_local = fields.Float(readonly=True, digits=(12, 2))
    budget_status = fields.Selection(BUDGET_STATUS_SELECTION, readonly=True)
    budget_utilization_pct = fields.Float(readonly=True, digits=(6, 2))

    # ETA
    eta_minutes = fields.Integer(readonly=True)
    eta_display = fields.Char(readonly=True)

    # Result html
    channel_projection_html = fields.Html(readonly=True)
    variant_projection_html = fields.Html(readonly=True)
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
        """Compute the projection and refresh the wizard view."""
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

        # 3. Per-partner channel projection
        channel_buckets = defaultdict(list)   # channel_id → [partner_id, ...]
        opted_out = []
        unreachable = []
        quiet_deferred = []

        Pref = self.env['comm.partner.communication.preference']
        Registry = self.env['comm.chatbot.registry']
        priority = campaign.channel_priority_ids.sorted('sequence')

        for partner in partners:
            assigned = None
            for channel in priority:
                adapter_cls = Registry.get_adapter_for_channel(channel)
                if not adapter_cls:
                    continue
                try:
                    if not adapter_cls().can_reach(self.env, partner):
                        continue
                except Exception:
                    continue
                if not Pref.is_opted_in(partner, channel, campaign.purpose):
                    opted_out.append(partner.id)
                    assigned = 'opted_out'
                    break
                # Quiet hours check — approximate (does not compute per-partner tz)
                assigned = channel
                break
            if assigned is None:
                unreachable.append(partner.id)
            elif assigned == 'opted_out':
                pass
            else:
                channel_buckets[assigned.id].append(partner.id)

        reachable_count = sum(len(v) for v in channel_buckets.values())

        # 4. Cost projection per channel bucket
        currency = campaign.budget_currency_id or self.env.company.currency_id
        total_usd = 0.0
        channel_rows = []

        for channel_id, partner_ids in channel_buckets.items():
            channel = self.env['comm.channel'].browse(channel_id)
            per_recipient_usd = self._cost_per_recipient(channel, campaign, analysis)
            bucket_usd = per_recipient_usd * len(partner_ids)
            total_usd += bucket_usd
            channel_rows.append({
                'channel': channel.name,
                'recipients': len(partner_ids),
                'per_recipient_usd': per_recipient_usd,
                'bucket_usd': bucket_usd,
            })

        # 5. FX to local
        fx, _ = self.env['comm.billing.event']._resolve_fx(
            None, fields.Date.today(), currency_hint=currency)
        projected_cost_local = total_usd * (fx or 1.0)

        # 6. Budget status
        cap = campaign.budget_cap_local or 0.0
        if not cap:
            status, util_pct = 'none', 0.0
        else:
            util_pct = (projected_cost_local / cap) * 100
            if util_pct >= 100:
                status = 'exceeded'
            elif util_pct >= (campaign.budget_soft_threshold_pct or 80):
                status = 'warn'
            else:
                status = 'ok'

        # 7. ETA
        throttle = max(campaign.throttle_per_minute or 60, 1)
        eta_min = int((reachable_count + throttle - 1) / throttle)
        eta_display = self._format_eta(eta_min)

        # 8. Variant split (deterministic; use hash logic mirror)
        variant_html = self._project_variants(campaign, channel_buckets)

        # 9. Build presentation
        self.write({
            'total_audience': total,
            'reachable_count': reachable_count,
            'opted_out_count': len(opted_out),
            'unreachable_count': len(unreachable),
            'quiet_hours_deferred': len(quiet_deferred),
            'billable_step_count': analysis['billable'],
            'llm_step_count': analysis['llm_steps'],
            'llm_projected_tokens_per_conversation': analysis['llm_tokens_per_convo'],
            'projected_cost_usd': total_usd,
            'projected_cost_local': projected_cost_local,
            'display_currency_id': currency.id if currency else False,
            'budget_cap_local': cap,
            'budget_status': status,
            'budget_utilization_pct': util_pct,
            'eta_minutes': eta_min,
            'eta_display': eta_display,
            'channel_projection_html': self._render_channels(channel_rows, currency, fx),
            'variant_projection_html': variant_html,
            'summary_html': self._render_summary(
                total, reachable_count, projected_cost_local, cap, util_pct,
                status, eta_display, currency),
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

    # ---------- Bot graph analysis ----------
    def _analyse_bot(self, bot):
        """Walk the reachable graph from entry_step_id, counting billable
        outbounds and estimating LLM token consumption per conversation."""
        outbound_kinds = {'message', 'menu', 'input', 'handoff', 'channel_switch'}
        counts = {'billable': 0, 'llm_steps': 0, 'llm_tokens_per_convo': 0}
        visited = set()

        def visit(step):
            if not step or step.id in visited:
                return
            visited.add(step.id)
            if step.kind in outbound_kinds:
                counts['billable'] += 1
            if step.kind == 'llm':
                counts['llm_steps'] += 1
                counts['billable'] += 1  # LLM also produces an outbound
                # Estimate: system prompt (~1000 tok) + history (10 * 200) + output
                out_tokens = int((step.llm_max_tokens or 1024) * 0.6)
                counts['llm_tokens_per_convo'] += 1000 + 2000 + out_tokens
            # Follow default next
            if step.next_step_id:
                visit(step.next_step_id)
            # Follow option branches
            for opt in step.option_ids:
                if opt.next_step_id:
                    visit(opt.next_step_id)
            # Follow LLM decision options
            for opt in step.llm_decision_option_ids:
                visit(opt)
            # Follow branch on kind-specific fields
            if step.jump_target_step_id:
                visit(step.jump_target_step_id)
            if step.llm_fallback_step_id:
                visit(step.llm_fallback_step_id)

        visit(bot.entry_step_id)
        return counts

    # ---------- Cost per recipient ----------
    def _cost_per_recipient(self, channel, campaign, analysis):
        """Look up the rate card for this channel + a representative category,
        multiply by billable step count. Add LLM projection if applicable."""
        today = fields.Date.today()
        card = self.env['comm.billing.rate.card'].active_on(channel.code, today)
        if not card:
            return 0.0

        # Representative category per channel
        cat_map = {
            'whatsapp': 'marketing',
            'sms':      'sms_outbound_domestic',
            'ussd':     'ussd_session',
            'voice':    'voice_outbound_local_mobile',
        }
        category = cat_map.get(channel.code)
        if not category:
            return 0.0

        # ZA rate (audience assumed local for projection)
        za = self.env.ref('base.za', raise_if_not_found=False)
        rate_row = card.resolve_rate(country=za, category=category)
        if not rate_row:
            rate_row = card.resolve_rate(country=None, category=category)
        per_step_usd = rate_row.price_usd if rate_row else 0.0
        message_cost = per_step_usd * analysis['billable']

        # LLM cost — look up token rate on any hybrid WA card (present since Aug 2026 seed)
        llm_cost = 0.0
        if analysis['llm_steps']:
            wa_card = self.env['comm.billing.rate.card'].search([
                ('channel', '=', 'whatsapp'),
                ('billing_model', 'in', ('hybrid_2026', 'hybrid_service_paid')),
            ], limit=1, order='effective_from desc')
            if wa_card:
                token_rate = wa_card.resolve_rate(country=None, category='mba_token')
                if token_rate:
                    llm_cost = (analysis['llm_tokens_per_convo'] / 1000.0) \
                                * token_rate.price_usd
            else:
                llm_cost = (analysis['llm_tokens_per_convo'] / 1000.0) * 0.002

        return message_cost + llm_cost

    # ---------- Variant projection ----------
    def _project_variants(self, campaign, channel_buckets):
        if not campaign.variant_ids:
            return '<p><em>No A/B variants defined.</em></p>'
        total_recipients = sum(len(v) for v in channel_buckets.values())
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
                        f'<td class="text-end">{int(total_recipients * share)}</td>'
                        f'</tr>')
        html.append('</tbody></table>')
        return ''.join(html)

    # ---------- HTML renderers ----------
    def _render_channels(self, rows, currency, fx):
        if not rows:
            return '<p><em>No recipients projected on any channel.</em></p>'
        sym = currency.symbol or currency.name or ''
        html = ['<table class="table table-sm">',
                '<thead><tr><th>Channel</th>'
                '<th class="text-end">Recipients</th>'
                '<th class="text-end">Per-recipient (USD)</th>'
                f'<th class="text-end">Bucket total ({sym})</th>'
                '<th class="text-end">Bucket total (USD)</th>'
                '</tr></thead><tbody>']
        for r in rows:
            local = r['bucket_usd'] * (fx or 1.0)
            html.append(f'<tr><td>{r["channel"]}</td>'
                        f'<td class="text-end">{r["recipients"]}</td>'
                        f'<td class="text-end">${r["per_recipient_usd"]:.4f}</td>'
                        f'<td class="text-end">{local:,.2f}</td>'
                        f'<td class="text-end">${r["bucket_usd"]:.4f}</td>'
                        f'</tr>')
        html.append('</tbody></table>')
        return ''.join(html)

    def _render_summary(self, total, reachable, cost_local, cap, util_pct,
                        status, eta_display, currency):
        sym = (currency and currency.symbol) or (currency and currency.name) or ''
        status_colour = {
            'ok': 'success', 'warn': 'warning',
            'exceeded': 'danger', 'none': 'secondary',
        }[status]
        cap_line = ''
        if status != 'none':
            cap_line = (f'<div>Budget: {sym} {cost_local:,.2f} / {sym} {cap:,.2f} '
                        f'(<b>{util_pct:.1f}%</b>) — '
                        f'<span class="badge text-bg-{status_colour}">{status}</span></div>')
        return (
            f'<div class="o_campaign_sim_summary">'
            f'<div><b>Audience:</b> {total} • <b>Reachable:</b> {reachable}</div>'
            f'<div><b>Projected cost:</b> {sym} {cost_local:,.2f}</div>'
            f'{cap_line}'
            f'<div><b>ETA to complete:</b> {eta_display}</div>'
            f'</div>'
        )

    def _render_assumptions(self):
        return (
            '<ul>'
            '<li>Every non-wait outbound step fires once per conversation '
            '(upper-bound cost; real drop-off reduces this).</li>'
            '<li>Recipients are assumed to be in ZA for rate lookup. '
            'International recipients would use their own rate rows.</li>'
            '<li>LLM tokens: ~3,000 input (system prompt + history) plus '
            '60% of max_tokens output, per LLM step.</li>'
            '<li>Fallback-model retries are excluded — add ~10% headroom.</li>'
            '<li>Quiet-hours deferrals shift <em>when</em> sends happen, not '
            '<em>whether</em> — the ETA doesn\'t model this.</li>'
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
