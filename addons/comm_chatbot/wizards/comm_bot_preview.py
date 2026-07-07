# -*- coding: utf-8 -*-
"""Bot preview + interactive walker with per-channel tabs.

Opens from the bot form ("Preview" button). Two panels:
- Compare tab renders bot.entry_step_id on every allowed channel
  side-by-side so you can eyeball degradation (buttons on WA, numbered
  text on SMS, CON menu on USSD, DTMF prompt on voice).
- Walker tab lets you pick a channel and step through the full bot
  interactively (shadow mode by default so nothing is actually sent).

Distinct from the campaign simulator's walker — that one is scoped to
a campaign's audience and cost projection. This one is bot-scoped,
lightweight, and available even without a campaign.
"""
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


AWAITING_SELECTION = [
    ('none',  'None'),
    ('menu',  'Menu choice'),
    ('input', 'Free text'),
    ('done',  'Conversation ended'),
]


class CommBotPreview(models.TransientModel):
    _name = 'comm.bot.preview'
    _description = 'Bot preview + channel walker'

    bot_id = fields.Many2one('comm.bot', required=True, readonly=True)
    preview_partner_id = fields.Many2one('res.partner',
        string='Preview recipient',
        help='Whose profile drives variable substitution '
             '({{contact.first_name}} etc.).')

    # Static side-by-side render for the Compare tab
    comparison_html = fields.Html(readonly=True)

    # Walker state
    walker_channel_id = fields.Many2one('comm.channel',
        string='Walk on channel',
        help='Which channel to walk the bot on.')
    walker_active = fields.Boolean(default=False)
    walker_conversation_id = fields.Many2one('comm.conversation',
                                              readonly=True)
    walker_transcript_html = fields.Html(readonly=True)
    walker_current_prompt_html = fields.Html(readonly=True)
    walker_awaiting = fields.Selection(AWAITING_SELECTION, default='none',
                                       readonly=True)
    walker_input = fields.Char(string='Your reply')
    walker_spend_real_llm_tokens = fields.Boolean(
        string='Spend real LLM tokens',
        help='When on, LLM steps actually call the Anthropic API.')
    walker_spent_usd = fields.Float(readonly=True, digits=(12, 6))

    # ---------- Default_get: preselect from context ----------
    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        bot_id = self.env.context.get('active_id') \
            or self.env.context.get('default_bot_id')
        if bot_id:
            vals['bot_id'] = bot_id
            bot = self.env['comm.bot'].browse(bot_id)
            if bot.channel_ids:
                vals.setdefault('walker_channel_id', bot.channel_ids[:1].id)
        return vals

    # ---------- Public entry ----------
    def action_render_comparison(self):
        """Render entry step across every allowed channel and populate
        comparison_html."""
        self.ensure_one()
        if not self.bot_id or not self.bot_id.entry_step_id:
            raise UserError('Bot has no entry step to render.')
        self.comparison_html = self._render_comparison()
        return self._return_self()

    # ---------- Walker actions ----------
    def action_start_walker(self):
        self.ensure_one()
        bot = self.bot_id
        if not bot.entry_step_id:
            raise UserError('Bot has no entry step.')
        if not self.walker_channel_id:
            if bot.channel_ids:
                self.walker_channel_id = bot.channel_ids[:1]
            else:
                raise UserError('Bot has no allowed channels.')
        if not self.preview_partner_id:
            raise UserError('Pick a preview recipient before starting.')

        # Reset any prior walker conversation
        if self.walker_conversation_id:
            self.walker_conversation_id.sudo().unlink()

        conversation = self.env['comm.conversation'].create({
            'partner_id': self.preview_partner_id.id,
            'bot_id': bot.id,
            'primary_channel_id': self.walker_channel_id.id,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview_walker__',
            'lifecycle_state': 'open',
        })
        leg = self.env['comm.conversation.leg'].create({
            'conversation_id': conversation.id,
            'channel_id': self.walker_channel_id.id,
            'external_session_id': f'bot-preview-{self.id}',
        })

        ctx = {'comm_chatbot_force_shadow': True}
        if not self.walker_spend_real_llm_tokens:
            ctx['comm_chatbot_skip_llm'] = True
        self.env['comm.chatbot.executor'].with_context(**ctx).advance(
            conversation, leg)

        self.walker_conversation_id = conversation.id
        self.walker_active = True
        self._refresh_walker_view()
        return self._return_self()

    def action_walker_send(self):
        self.ensure_one()
        conversation = self.walker_conversation_id
        if not conversation:
            raise UserError('No active walker conversation.')
        leg = conversation.leg_ids.filtered(
            lambda l: l.channel_id == self.walker_channel_id)[:1]

        body = self.walker_input or ''
        self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': self.walker_channel_id.id,
            'direction': 'inbound',
            'raw_body': body,
            'status': 'received',
            'step_id': conversation.current_step_id.id
                       if conversation.current_step_id else False,
        })

        ctx = {'comm_chatbot_force_shadow': True}
        if not self.walker_spend_real_llm_tokens:
            ctx['comm_chatbot_skip_llm'] = True
        Exec = self.env['comm.chatbot.executor'].with_context(**ctx)
        if conversation.current_step_id and conversation.current_step_id.kind in (
                'menu', 'input'):
            Exec._handle_input(conversation, leg, body)
        else:
            Exec.advance(conversation, leg)

        self.walker_input = False
        self._refresh_walker_view()
        return self._return_self()

    def action_reset_walker(self):
        self.ensure_one()
        if self.walker_conversation_id:
            self.walker_conversation_id.sudo().unlink()
        self.walker_conversation_id = False
        self.walker_active = False
        self.walker_transcript_html = ''
        self.walker_current_prompt_html = ''
        self.walker_input = False
        self.walker_awaiting = 'none'
        self.walker_spent_usd = 0.0
        return self._return_self()

    @api.onchange('walker_channel_id')
    def _onchange_walker_channel(self):
        """Switching the walker channel resets the current run — a fresh
        conversation on the new channel."""
        if self.walker_active and self.walker_conversation_id:
            if self.walker_conversation_id.primary_channel_id != self.walker_channel_id:
                self.walker_conversation_id.sudo().unlink()
                self.walker_conversation_id = False
                self.walker_active = False
                self.walker_transcript_html = ''
                self.walker_current_prompt_html = ''
                self.walker_awaiting = 'none'
                self.walker_spent_usd = 0.0

    # ---------- Comparison rendering ----------
    def _render_comparison(self):
        bot = self.bot_id
        partner = self.preview_partner_id
        if not partner:
            return ('<div class="alert alert-warning">Pick a preview recipient '
                    'to render.</div>')

        # Create a temporary conversation for rendering (unlinked at end)
        conversation = self.env['comm.conversation'].create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': bot.channel_ids[:1].id if bot.channel_ids else False,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview_walker__',
            'lifecycle_state': 'open',
        })
        renderer = self.env['comm.chatbot.renderer']

        html = ['<div class="row">']
        try:
            for channel in bot.channel_ids.sorted('sequence'):
                conversation.primary_channel_id = channel
                try:
                    payload = renderer.render(bot.entry_step_id, conversation)
                    body = (payload.get('body') or '').replace('<', '&lt;')
                    options_html = ''
                    if payload.get('options'):
                        rendered_as = self._options_rendered_as(channel,
                                                                 len(payload['options']))
                        rows = ''.join(
                            f'<li>{o.get("label", "")}</li>'
                            for o in payload['options'])
                        options_html = (
                            f'<div class="mt-1"><small>'
                            f'Options ({rendered_as}):</small>'
                            f'<ul>{rows}</ul></div>'
                        )
                    media_html = ''
                    if payload.get('media'):
                        media_html = (
                            f'<div class="mt-1"><small>'
                            f'Media: {len(payload["media"])} '
                            f'attachment(s)</small></div>'
                        )
                    html.append(
                        f'<div class="col-md-6 mb-3">'
                        f'<div class="card">'
                        f'<div class="card-header"><b>📱 {channel.name}</b> '
                        f'<small class="text-muted">({channel.code}, '
                        f'max {channel.max_body_length or "∞"} chars)</small></div>'
                        f'<div class="card-body">'
                        f'<pre style="white-space: pre-wrap; margin: 0;">{body}</pre>'
                        f'{options_html}{media_html}'
                        f'</div></div></div>'
                    )
                except Exception as e:
                    html.append(
                        f'<div class="col-md-6 mb-3">'
                        f'<div class="alert alert-danger">'
                        f'<b>{channel.name}</b>: render error — {e}'
                        f'</div></div>'
                    )
        finally:
            conversation.sudo().unlink()

        html.append('</div>')
        return ''.join(html)

    def _options_rendered_as(self, channel, n_options):
        if channel.supports_lists and n_options <= (channel.max_list_rows or 10):
            return 'inline list'
        if channel.supports_buttons and n_options <= (channel.max_buttons or 3):
            return 'buttons'
        return 'numbered text embedded in body'

    # ---------- Walker view refresh ----------
    def _refresh_walker_view(self):
        conversation = self.walker_conversation_id
        if not conversation:
            return

        transcript = ['<div class="o_walker_transcript">']
        total_usd = 0.0
        for i in conversation.interaction_ids.sorted('at'):
            body = (i.rendered_body or i.raw_body or '').replace('<', '&lt;')
            llm_line = ''
            if i.direction == 'outbound' and (i.llm_input_tokens or i.llm_output_tokens):
                cost = self._cost_for_llm_interaction(i)
                total_usd += cost
                cache_line = ''
                if i.llm_cache_read_tokens or i.llm_cache_write_tokens:
                    cache_line = (f' • cache: {i.llm_cache_read_tokens:,} R / '
                                  f'{i.llm_cache_write_tokens:,} W')
                llm_line = (
                    f'<div class="mt-1"><small class="text-muted">'
                    f'⚡ {i.llm_model_used or "llm"} • '
                    f'{i.llm_input_tokens:,} in / {i.llm_output_tokens:,} out'
                    f'{cache_line} • ${cost:.4f}</small></div>'
                )
            if i.direction == 'outbound':
                transcript.append(
                    f'<div class="d-flex justify-content-start mb-2">'
                    f'<div class="p-2 rounded" style="background:#e9ecef; '
                    f'max-width: 75%;">'
                    f'<small class="text-muted">🤖 Bot ({i.step_id.name or "-"})</small>'
                    f'<pre style="white-space: pre-wrap; margin: 0.25rem 0 0 0;">'
                    f'{body}</pre>{llm_line}'
                    f'</div></div>'
                )
            else:
                transcript.append(
                    f'<div class="d-flex justify-content-end mb-2">'
                    f'<div class="p-2 rounded" style="background:#d1e7ff; '
                    f'max-width: 75%;">'
                    f'<small class="text-muted">👤 You</small>'
                    f'<pre style="white-space: pre-wrap; margin: 0.25rem 0 0 0;">'
                    f'{body}</pre>'
                    f'</div></div>'
                )
        transcript.append('</div>')
        self.walker_transcript_html = ''.join(transcript)
        self.walker_spent_usd = total_usd

        step = conversation.current_step_id
        if not step or conversation.lifecycle_state in ('closed', 'timeout'):
            self.walker_awaiting = 'done'
            self.walker_current_prompt_html = (
                f'<div class="alert alert-info">'
                f'<b>Conversation ended.</b> '
                f'Outcome: <code>{conversation.outcome or "—"}</code>'
                f'</div>'
            )
            return

        if step.kind == 'menu':
            self.walker_awaiting = 'menu'
            renderer = self.env['comm.chatbot.renderer']
            options = renderer._resolve_options(step, conversation)
            html = ['<div class="alert alert-secondary">'
                    f'<b>Waiting for your choice</b> at step <code>{step.name}</code>. '
                    'Reply with the number or the label:</div>'
                    '<ul>']
            for i, o in enumerate(options):
                html.append(f'<li><b>{i+1}</b> — {o.get("label", "")}'
                            f' <small class="text-muted">(value: '
                            f'{o.get("value", "")})</small></li>')
            html.append('</ul>')
            self.walker_current_prompt_html = ''.join(html)
        elif step.kind == 'input':
            self.walker_awaiting = 'input'
            hint = {
                'text':   'any text',
                'number': 'a number',
                'date':   'a date (YYYY-MM-DD)',
                'email':  'an email address',
                'phone':  'a phone number',
                'choice': 'the option value',
                'media':  '(media not supported in walker)',
            }.get(step.input_type or 'text', 'anything')
            self.walker_current_prompt_html = (
                f'<div class="alert alert-secondary">'
                f'<b>Waiting for input</b> at step <code>{step.name}</code>. '
                f'Reply with {hint}.'
                f'</div>'
            )
        else:
            self.walker_awaiting = 'none'
            self.walker_current_prompt_html = (
                f'<div class="alert alert-warning">'
                f'Stuck at <code>{step.name}</code> ({step.kind}). Send an '
                f'empty reply to advance.'
                f'</div>'
            )

    # ---------- Helpers ----------
    def _cost_for_llm_interaction(self, interaction):
        model = interaction.llm_model_used
        if not model:
            return 0.0
        buckets = [
            ('llm_input',       interaction.llm_input_tokens or 0),
            ('llm_output',      interaction.llm_output_tokens or 0),
            ('llm_cache_read',  interaction.llm_cache_read_tokens or 0),
            ('llm_cache_write', interaction.llm_cache_write_tokens or 0),
        ]
        card = self.env['comm.billing.rate.card'].search([
            ('channel', '=', 'other'),
            ('provider', '=', 'Anthropic'),
        ], limit=1, order='effective_from desc')
        total = 0.0
        for category, tokens in buckets:
            if not tokens or not card:
                continue
            rate = card.resolve_rate(carrier=model, category=category)
            if rate:
                total += (tokens / 1000.0) * rate.price_usd
        return total

    def _return_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
