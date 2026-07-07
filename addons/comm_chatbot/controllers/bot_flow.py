# -*- coding: utf-8 -*-
"""HTTP endpoint that returns an HTML page rendering the bot's flow via
Mermaid.js. Loaded from CDN to keep the module lightweight; falls back
gracefully with a plain-text diagram source if the CDN can't load.
"""
import logging
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
