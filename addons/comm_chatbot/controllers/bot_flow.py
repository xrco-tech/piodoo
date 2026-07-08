# -*- coding: utf-8 -*-
"""HTTP + JSON-RPC endpoints for the bot flow client action.

- /comm_chatbot/bot_flow/<id>  legacy Mermaid HTML fallback (kept)
- /comm_chatbot/bot_flow/tree  JSON tree of bot steps for the canvas
- /comm_chatbot/bot_flow/simulate/*  simulator plumbing (delegates to
  comm.chatbot.executor via context flags — same shape as the Preview
  wizard's walker, no adapter sends, LLM optional).
"""
import logging
import uuid
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class BotFlowController(http.Controller):

    @http.route('/comm_chatbot/bot_flow/<int:bot_id>',
                type='http', auth='user', methods=['GET'], csrf=False)
    def render_bot_flow(self, bot_id, **kwargs):
        bot = request.env['comm.bot'].browse(bot_id)
        if not bot.exists():
            return request.not_found()

        base_url = request.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '') or ''
        mermaid_source = bot._render_mermaid_source(base_url=base_url)

        html = _FLOW_HTML_TEMPLATE.format(
            bot_name=(bot.name or '').replace('<', '&lt;'),
            step_count=len(bot.step_ids),
            engine_mode=bot.engine_mode or '',
            base_url=base_url,
            bot_id=bot.id,
            channels=', '.join(bot.channel_ids.mapped('name')) or '—',
            mermaid_source=mermaid_source,
        )
        return request.make_response(
            html, headers=[('Content-Type', 'text/html; charset=utf-8')])


_FLOW_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>{bot_name} — Flow diagram</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                background: #f5f7fa; color: #212529; }}
        .header {{ background: #263238; color: #fff; padding: 12px 20px;
                   display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ font-size: 18px; margin: 0; font-weight: 500; }}
        .header .meta {{ font-size: 13px; opacity: 0.8; }}
        .header a {{ color: #90caf9; text-decoration: none; margin-left: 15px; }}
        .header a:hover {{ text-decoration: underline; }}
        .toolbar {{ padding: 8px 20px; background: #eceff1; border-bottom: 1px solid #cfd8dc;
                     display: flex; gap: 10px; align-items: center; font-size: 13px; }}
        .toolbar button {{ background: #fff; border: 1px solid #b0bec5; border-radius: 4px;
                            padding: 4px 12px; cursor: pointer; }}
        .toolbar button:hover {{ background: #f5f5f5; }}
        .diagram-wrap {{ padding: 20px; min-height: calc(100vh - 100px); }}
        .diagram {{ background: #fff; border: 1px solid #cfd8dc; border-radius: 6px;
                    padding: 20px; overflow: auto; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
        .legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px;
                    padding: 12px; background: #fff; border-radius: 6px;
                    border: 1px solid #cfd8dc; font-size: 12px; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; }}
        .swatch {{ display: inline-block; width: 14px; height: 14px; border-radius: 3px;
                    border: 1px solid rgba(0,0,0,0.15); }}
        pre.mermaid-source {{ background: #263238; color: #eceff1; padding: 12px;
                              border-radius: 4px; font-size: 11px; overflow: auto;
                              max-height: 300px; display: none; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🤖 {bot_name}</h1>
            <div class="meta">
                {step_count} steps • engine: <b>{engine_mode}</b> •
                channels: <b>{channels}</b>
            </div>
        </div>
        <div>
            <a href="{base_url}/odoo/action-comm_chatbot.action_comm_bot/{bot_id}"
               target="_blank">← Back to bot</a>
            <a href="#" onclick="toggleSource();return false;">Toggle source</a>
        </div>
    </div>

    <div class="toolbar">
        <button onclick="doZoomIn()">Zoom +</button>
        <button onclick="doZoomOut()">Zoom −</button>
        <button onclick="doReset()">Reset</button>
        <span style="color:#546e7a">Click any node to open its step form in a new tab.</span>
    </div>

    <div class="diagram-wrap">
        <div class="diagram">
            <pre class="mermaid">
{mermaid_source}
            </pre>
        </div>
        <pre class="mermaid-source" id="mermaid-source">{mermaid_source}</pre>
        <div class="legend">
            <span class="legend-item"><span class="swatch" style="background:#e3f2fd;border-color:#1976d2"></span> Message</span>
            <span class="legend-item"><span class="swatch" style="background:#fff3e0;border-color:#f57c00"></span> Menu</span>
            <span class="legend-item"><span class="swatch" style="background:#f3e5f5;border-color:#7b1fa2"></span> Input</span>
            <span class="legend-item"><span class="swatch" style="background:#fce4ec;border-color:#c2185b"></span> Condition</span>
            <span class="legend-item"><span class="swatch" style="background:#e0f2f1;border-color:#00796b"></span> Action</span>
            <span class="legend-item"><span class="swatch" style="background:#fff9c4;border-color:#f9a825"></span> Handoff</span>
            <span class="legend-item"><span class="swatch" style="background:#e8f5e9;border-color:#388e3c"></span> LLM</span>
            <span class="legend-item"><span class="swatch" style="background:#c8e6c9;border-color:#388e3c"></span> End</span>
            <span class="legend-item"><span class="swatch" style="background:#37474f;border-color:#263238"></span> Entry</span>
            <span class="legend-item"><span class="swatch" style="background:#e1f5fe;border-color:#0288d1"></span> Channel switch</span>
        </div>
    </div>

    <script>
        var panZoomInstance = null;
        function initPanZoom() {{
            var svg = document.querySelector('.diagram svg');
            if (!svg || !window.svgPanZoom) return;
            panZoomInstance = svgPanZoom(svg, {{
                zoomEnabled: true,
                controlIconsEnabled: false,
                fit: true, center: true, minZoom: 0.2, maxZoom: 10,
            }});
        }}
        function doZoomIn()  {{ panZoomInstance && panZoomInstance.zoomIn();  }}
        function doZoomOut() {{ panZoomInstance && panZoomInstance.zoomOut(); }}
        function doReset()   {{ panZoomInstance && panZoomInstance.resetZoom() && panZoomInstance.center(); }}
        function toggleSource() {{
            var el = document.getElementById('mermaid-source');
            el.style.display = (el.style.display === 'block') ? 'none' : 'block';
        }}

        mermaid.initialize({{
            startOnLoad: false,
            theme: 'default',
            flowchart: {{ curve: 'basis', htmlLabels: true }},
            securityLevel: 'loose',
        }});
        mermaid.run().then(initPanZoom);
    </script>
</body>
</html>
"""


# ── JSON-RPC endpoints for the OWL client action ─────────────────────

class BotFlowJsonController(http.Controller):

    @http.route('/comm_chatbot/bot_flow/tree', type='json', auth='user')
    def bot_flow_tree(self, bot_id, **kwargs):
        bot = request.env['comm.bot'].browse(bot_id)
        if not bot.exists():
            return {'error': 'bot not found'}

        # Build a rooted tree from entry_step_id following next_step_id +
        # option branches. Steps not reachable from entry still get emitted
        # as top-level "orphan" nodes.
        seen = set()
        tree = []
        if bot.entry_step_id:
            tree.append(_step_to_node(bot.entry_step_id, seen))
        for step in bot.step_ids:
            if step.id not in seen:
                tree.append(_step_to_node(step, seen))

        return {
            'bot_id': bot.id,
            'bot_name': bot.name,
            'channels': [{'code': c.code, 'name': c.name}
                          for c in bot.channel_ids],
            'variables': [{'name': v.name, 'type': v.type,
                            'default_value': v.default_value}
                           for v in bot.variable_ids],
            'tree': tree,
        }

    @http.route('/comm_chatbot/bot_flow/simulate/start', type='json', auth='user')
    def simulate_start(self, bot_id, channel_code, persona_name=None,
                       persona_mobile=None, spend_real_llm_tokens=False,
                       variables=None, **kwargs):
        env = request.env
        bot = env['comm.bot'].browse(bot_id)
        if not bot.exists() or not bot.entry_step_id:
            return {'error': 'bot has no entry step'}
        channel = env['comm.channel'].get_by_code(channel_code)
        if not channel:
            return {'error': f'unknown channel {channel_code}'}

        # Create / reuse a preview partner
        Partner = env['res.partner'].sudo()
        persona = Partner.search([
            ('mobile', '=', persona_mobile),
        ], limit=1)
        if not persona:
            persona = Partner.create({
                'name': persona_name or 'Simulator user',
                'mobile': persona_mobile or '+27600000000',
                'whatsapp_id': persona_mobile or '',
            })

        conversation = env['comm.conversation'].create({
            'partner_id': persona.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview_walker__',
            'lifecycle_state': 'open',
            'state': dict(variables or {}),
        })
        leg = env['comm.conversation.leg'].create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'external_session_id': f'bot-flow-{uuid.uuid4().hex[:8]}',
        })

        ctx = {'comm_chatbot_force_shadow': True}
        if not spend_real_llm_tokens:
            ctx['comm_chatbot_skip_llm'] = True
        env['comm.chatbot.executor'].with_context(**ctx).advance(
            conversation, leg)

        return _sim_response(env, conversation, str(conversation.id))

    @http.route('/comm_chatbot/bot_flow/simulate/reply', type='json', auth='user')
    def simulate_reply(self, session_id, user_input, **kwargs):
        env = request.env
        conversation = env['comm.conversation'].browse(int(session_id))
        if not conversation.exists():
            return {'error': 'session not found'}
        leg = conversation.leg_ids.filtered(lambda l: not l.closed_at)[:1]

        env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': conversation.primary_channel_id.id,
            'direction': 'inbound',
            'raw_body': user_input or '',
            'status': 'received',
            'step_id': conversation.current_step_id.id
                       if conversation.current_step_id else False,
        })

        ctx = {'comm_chatbot_force_shadow': True,
               'comm_chatbot_skip_llm': True}
        Exec = env['comm.chatbot.executor'].with_context(**ctx)
        step = conversation.current_step_id
        if step and step.kind in ('menu', 'input'):
            Exec._handle_input(conversation, leg, user_input or '')
        else:
            Exec.advance(conversation, leg)

        return _sim_response(env, conversation, session_id)

    @http.route('/comm_chatbot/bot_flow/simulate/reset', type='json', auth='user')
    def simulate_reset(self, session_id, **kwargs):
        env = request.env
        conversation = env['comm.conversation'].browse(int(session_id))
        if conversation.exists():
            conversation.sudo().unlink()
        return {'ok': True}


# ── Helpers ──────────────────────────────────────────────────────────

def _step_to_node(step, seen, depth=0):
    """Recursively build a tree node with children from step + option branches."""
    if step.id in seen or depth > 40:
        # Reference-only node (cycles or depth guard) — no children
        return {
            'id': step.id, 'name': step.name, 'kind': step.kind,
            'preview': ('… ' + (step.body or '')[:30]) if step.body else '',
            'children': [],
        }
    seen.add(step.id)
    body = (step.body or '').strip()
    preview = body[:60] + ('…' if len(body) > 60 else '')
    node = {
        'id': step.id, 'name': step.name, 'kind': step.kind,
        'preview': preview,
        'body': step.body or '',
        'input_type': step.input_type,
        'save_to': step.input_save_to,
        'llm_model': step.llm_model,
        'llm_output_mode': step.llm_output_mode,
        'options': [{
            'label': o.label,
            'value': o.value,
            'next_step_name': o.next_step_id.name if o.next_step_id else '',
        } for o in step.option_ids.sorted('sequence')],
        'children': [],
    }
    # Determine children — for menu/condition, follow option branches;
    # otherwise follow next_step_id.
    if step.kind in ('menu', 'condition'):
        for opt in step.option_ids.sorted('sequence'):
            if opt.next_step_id:
                node['children'].append(_step_to_node(opt.next_step_id,
                                                      seen, depth + 1))
    else:
        if step.next_step_id:
            node['children'].append(_step_to_node(step.next_step_id,
                                                   seen, depth + 1))
    return node


def _sim_response(env, conversation, session_id):
    """Serialize interactions + current wait state."""
    messages = []
    total_llm_usd = 0.0
    token_prices_cache = {}

    def _rate(carrier, category):
        key = (carrier, category)
        if key in token_prices_cache:
            return token_prices_cache[key]
        card = env['comm.billing.rate.card'].search([
            ('channel', '=', 'other'),
            ('provider', '=', 'Anthropic'),
        ], limit=1, order='effective_from desc')
        rate = 0.0
        if card:
            row = card.resolve_rate(carrier=carrier, category=category)
            if row:
                rate = row.price_usd
        token_prices_cache[key] = rate
        return rate

    for i in conversation.interaction_ids.sorted('at'):
        entry = {
            'direction': i.direction,
            'body': i.rendered_body or i.raw_body or '',
            'step_name': i.step_id.name if i.step_id else '',
        }
        if i.direction == 'outbound' and (i.llm_input_tokens or i.llm_output_tokens):
            model = i.llm_model_used or ''
            cost = (
                (i.llm_input_tokens or 0)  / 1000.0 * _rate(model, 'llm_input') +
                (i.llm_output_tokens or 0) / 1000.0 * _rate(model, 'llm_output') +
                (i.llm_cache_read_tokens or 0)  / 1000.0 * _rate(model, 'llm_cache_read') +
                (i.llm_cache_write_tokens or 0) / 1000.0 * _rate(model, 'llm_cache_write')
            )
            total_llm_usd += cost
            entry['llm'] = {
                'model': model,
                'tokens_in': i.llm_input_tokens or 0,
                'tokens_out': i.llm_output_tokens or 0,
                'cost': cost,
            }
        messages.append(entry)

    step = conversation.current_step_id
    waiting = 'none'
    current_options = []
    if not step or conversation.lifecycle_state in ('closed', 'timeout'):
        waiting = 'done'
    elif step.kind == 'menu':
        waiting = 'menu'
        current_options = [{
            'label': o.label, 'value': o.value or o.label,
        } for o in step.option_ids.sorted('sequence')]
    elif step.kind == 'input':
        waiting = 'input'

    return {
        'session_id': session_id,
        'messages': messages,
        'waiting': waiting,
        'current_step_id': step.id if step else None,
        'current_options': current_options,
        'spent_usd': total_llm_usd,
    }
