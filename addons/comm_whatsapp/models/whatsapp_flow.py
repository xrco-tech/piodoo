# -*- coding: utf-8 -*-

import logging
import requests
import json
from markupsafe import Markup, escape
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WhatsAppFlow(models.Model):
    _name = 'whatsapp.flow'
    _description = 'WhatsApp Flow'
    _order = 'name, id desc'
    _rec_name = 'name'

    # Flow identifiers
    name = fields.Char(string='Flow Name', required=True, index=True,
                      help='Flow name (lowercase alphanumeric and underscores only)')
    flow_id_meta = fields.Char(string='Meta Flow ID', readonly=True,
                               help='Flow ID returned from Meta API')
    
    # Flow status
    status = fields.Selection([
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('DEPRECATED', 'Deprecated'),
        ('THROTTLED', 'Throttled'),
        ('BLOCKED', 'Blocked'),
    ], string='Status', readonly=True, default='DRAFT', index=True,
       help='Flow status: Draft (editing), Published (can be used), etc.')
    
    # Authoring mode. When use_raw_json=False (default), users build the flow
    # via the Screens / Components tabs and flow_json is generated for them.
    # When True, users edit flow_json directly — escape hatch for advanced
    # cases or imported flows.
    use_raw_json = fields.Boolean(
        string='Edit JSON directly',
        help="By default, flows are built via the Screens tab and the JSON is "
             "generated automatically. Tick this to edit the raw Flow JSON "
             "directly (useful when adopting a flow authored elsewhere).",
    )

    # Schema version Meta expects. Update default when a new version ships.
    flow_version = fields.Char(
        string='Flow Version', default='7.0', required=True,
        help="WhatsApp Flow JSON schema version. See Meta docs for current "
             "supported versions.",
    )

    # Flow JSON definition. ALWAYS required at the DB level so Meta has
    # something to upload. When use_raw_json=False, this is rebuilt on save
    # from the structured records (screens/components/options).
    flow_json = fields.Text(string='Flow JSON', required=True, default='{}',
                            help='Flow definition in JSON format. Auto-generated '
                                 'from screens/components unless raw mode is on.')
    flow_json_formatted = fields.Text(string='Flow JSON (Formatted)', compute='_compute_flow_json_formatted')

    # Structured authoring relations
    screen_ids = fields.One2many(
        'whatsapp.flow.screen', 'flow_id', string='Screens',
    )
    screen_count = fields.Integer(
        string='Screens', compute='_compute_screen_count', store=True,
    )

    # Validation feedback — shown on its own tab as a list of issues. Recomputed
    # whenever screens / components / options change so authors get instant feedback.
    validation_issues = fields.Text(
        string='Validation Issues',
        compute='_compute_validation_issues',
        help="Issues that would prevent Meta from accepting the flow.",
    )
    validation_status = fields.Selection([
        ('ok',       'OK'),
        ('warning',  'Warnings'),
        ('error',    'Errors'),
    ], compute='_compute_validation_issues', store=False)

    # Flow map — server-rendered SVG showing screens as boxes and navigate
    # actions as arrows. Recomputed live so authors can see the structure
    # update as they wire screens together.
    flow_map_svg = fields.Html(
        string='Flow Map', compute='_compute_flow_map_svg', sanitize=False,
        help="Visual overview of how screens connect via navigate actions.",
    )
    
    # Flow metadata
    description = fields.Text(string='Description', help='Flow description for internal use')
    category = fields.Char(string='Category', help='Flow category (e.g., lead_generation, booking)')
    
    # Meta information
    version = fields.Char(string='Version', readonly=True, help='Flow version from Meta')
    created_time = fields.Datetime(string='Created Time', readonly=True)
    updated_time = fields.Datetime(string='Updated Time', readonly=True)
    
    # Usage tracking
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True,
                                help='Number of times this flow has been used')
    last_used = fields.Datetime(string='Last Used', readonly=True)
    
    # First page ID (needed for sending)
    first_page_id = fields.Char(string='First Page ID', readonly=True,
                               help='ID of the first screen/page in the flow')
    
    # Preview information
    preview_url = fields.Char(string='Preview URL', readonly=True,
                             help='URL to preview the flow')
    preview_url_expiry_date = fields.Datetime(string='Preview URL Expiry Date', readonly=True,
                                            help='When the preview URL expires')

    @api.depends('flow_json')
    def _compute_flow_json_formatted(self):
        """Format JSON for display"""
        for record in self:
            try:
                if record.flow_json:
                    parsed = json.loads(record.flow_json)
                    record.flow_json_formatted = json.dumps(parsed, indent=2)
                else:
                    record.flow_json_formatted = ''
            except (json.JSONDecodeError, ValueError):
                record.flow_json_formatted = record.flow_json or ''

    @api.depends('screen_ids')
    def _compute_screen_count(self):
        for rec in self:
            rec.screen_count = len(rec.screen_ids)

    @api.depends(
        'use_raw_json', 'flow_version',
        'screen_ids', 'screen_ids.screen_id', 'screen_ids.title',
        'screen_ids.terminal', 'screen_ids.success', 'screen_ids.data_schema',
        'screen_ids.component_ids',
        'screen_ids.component_ids.component_type',
        'screen_ids.component_ids.name', 'screen_ids.component_ids.label',
        'screen_ids.component_ids.text', 'screen_ids.component_ids.helper_text',
        'screen_ids.component_ids.required',
        'screen_ids.component_ids.input_type',
        'screen_ids.component_ids.min_chars', 'screen_ids.component_ids.max_chars',
        'screen_ids.component_ids.init_value',
        'screen_ids.component_ids.min_selected', 'screen_ids.component_ids.max_selected',
        'screen_ids.component_ids.min_date', 'screen_ids.component_ids.max_date',
        'screen_ids.component_ids.image_src', 'screen_ids.component_ids.image_alt',
        'screen_ids.component_ids.image_height', 'screen_ids.component_ids.image_scale',
        'screen_ids.component_ids.photo_source',
        'screen_ids.component_ids.min_uploaded', 'screen_ids.component_ids.max_uploaded',
        'screen_ids.component_ids.max_file_size_kb',
        'screen_ids.component_ids.action_type',
        'screen_ids.component_ids.target_screen_id',
        'screen_ids.component_ids.open_url',
        'screen_ids.component_ids.payload_keys',
        'screen_ids.component_ids.option_ids',
        'screen_ids.component_ids.option_ids.option_id',
        'screen_ids.component_ids.option_ids.title',
        'screen_ids.component_ids.option_ids.description',
        'screen_ids.component_ids.option_ids.enabled',
        'screen_ids.component_ids.option_ids.sequence',
    )
    def _compute_validation_issues(self):
        """Run the validator on every change. Stores nothing — just a
        computed text + status flag so the form view shows live feedback."""
        for rec in self:
            if rec.use_raw_json:
                # In raw mode, the validator can't introspect — assume OK
                # unless the JSON itself is malformed.
                try:
                    if rec.flow_json:
                        json.loads(rec.flow_json)
                    rec.validation_issues = ''
                    rec.validation_status = 'ok'
                except (json.JSONDecodeError, ValueError) as e:
                    rec.validation_issues = f"Raw JSON parse error: {e}"
                    rec.validation_status = 'error'
                continue
            issues = rec._validate_structured()
            errors = [i for i in issues if i['level'] == 'error']
            warns  = [i for i in issues if i['level'] == 'warning']
            if errors:
                rec.validation_status = 'error'
            elif warns:
                rec.validation_status = 'warning'
            else:
                rec.validation_status = 'ok'
            rec.validation_issues = '\n'.join(
                f"[{i['level'].upper()}] {i['where']}: {i['message']}"
                for i in issues
            ) or 'No issues found.'

    # ── Flow map action handlers ────────────────────────────────────────

    def action_open_flow_map(self):
        """Open the dedicated full-screen Map view for this flow."""
        self.ensure_one()
        return {
            'type':       'ir.actions.act_window',
            'name':       f'Map — {self.name}',
            'res_model':  'whatsapp.flow',
            'res_id':     self.id,
            'view_mode':  'form',
            'view_id':    self.env.ref(
                'comm_whatsapp.view_whatsapp_flow_map_form').id,
            'target':     'current',
        }

    def action_back_to_flow_form(self):
        """Return from the Map view to the regular flow form."""
        self.ensure_one()
        return {
            'type':       'ir.actions.act_window',
            'name':       self.name,
            'res_model':  'whatsapp.flow',
            'res_id':     self.id,
            'view_mode':  'form',
            'view_id':    self.env.ref(
                'comm_whatsapp.view_whatsapp_flow_form').id,
            'target':     'current',
        }

    # ── Flow map (server-rendered SVG) ──────────────────────────────────

    @api.depends(
        'use_raw_json',
        'screen_ids', 'screen_ids.screen_id', 'screen_ids.title',
        'screen_ids.sequence', 'screen_ids.terminal', 'screen_ids.success',
        'screen_ids.component_count',
        'screen_ids.component_ids',
        'screen_ids.component_ids.action_type',
        'screen_ids.component_ids.target_screen_id',
        'screen_ids.component_ids.label',
        'screen_ids.component_ids.open_url',
    )
    def _compute_flow_map_svg(self):
        for rec in self:
            if rec.use_raw_json:
                rec.flow_map_svg = Markup(
                    '<div class="text-muted small">'
                    'Flow map is only available in structured mode. '
                    'Untick <strong>Edit JSON directly</strong> to use it.'
                    '</div>'
                )
                continue
            if not rec.screen_ids:
                rec.flow_map_svg = Markup(
                    '<div class="text-muted small">'
                    'Add at least one screen to see the flow map.'
                    '</div>'
                )
                continue
            rec.flow_map_svg = Markup(rec._build_map_svg())

    def _build_map_svg(self):
        """Layered top-down SVG: screens as boxes, navigate actions as arrows."""
        self.ensure_one()
        screens = self.screen_ids.sorted('sequence')
        by_id = {s.screen_id: s for s in screens}

        # Adjacency: screen_id -> list of {to, label, kind}
        edges = {s.screen_id: [] for s in screens}
        external = []   # open_url targets — drawn as little side nodes
        completes = []  # screens whose action is "complete" — drawn as end pill
        for s in screens:
            for c in s.component_ids.sorted('sequence'):
                if c.action_type == 'navigate' and c.target_screen_id \
                   and c.target_screen_id.screen_id in by_id:
                    edges[s.screen_id].append({
                        'to': c.target_screen_id.screen_id,
                        'label': (c.label or 'navigate')[:18],
                        'kind': 'navigate',
                    })
                elif c.action_type == 'complete':
                    completes.append((s.screen_id, (c.label or 'complete')[:18]))
                elif c.action_type == 'open_url' and c.open_url:
                    external.append((s.screen_id, c.open_url[:32],
                                     (c.label or 'open URL')[:18]))

        # BFS levels from the first screen (by sequence).
        first = screens[0].screen_id
        levels = {first: 0}
        queue = [first]
        while queue:
            cur = queue.pop(0)
            for e in edges.get(cur, []):
                t = e['to']
                nxt = levels[cur] + 1
                if t not in levels:
                    levels[t] = nxt
                    queue.append(t)
                elif levels[t] < nxt:
                    # Push existing node deeper so arrows go downward.
                    levels[t] = nxt
                    queue.append(t)
        # Orphans (no inbound or outbound edge from entry) — append at the bottom.
        max_level = max(levels.values()) if levels else 0
        for s in screens:
            if s.screen_id not in levels:
                max_level += 1
                levels[s.screen_id] = max_level

        by_level = {}
        for sid, lvl in levels.items():
            by_level.setdefault(lvl, []).append(sid)
        # Stable order inside a level: by sequence.
        for lvl in by_level:
            by_level[lvl].sort(key=lambda sid: by_id[sid].sequence)

        BOX_W, BOX_H = 210, 92
        HGAP, VGAP = 50, 90
        PAD = 30
        # Extra side gutters so off-box pills (open URL on the left, complete
        # under the source box) don't get clipped by the SVG canvas.
        EXTRA_LEFT = 170 if external else 0
        EXTRA_BOTTOM = 60 if completes else 0
        max_per_row = max(len(r) for r in by_level.values())
        screen_area_w = max_per_row * BOX_W + (max_per_row - 1) * HGAP
        svg_w = PAD * 2 + EXTRA_LEFT + screen_area_w
        svg_h = PAD * 2 + (max(by_level) + 1) * (BOX_H + VGAP) + EXTRA_BOTTOM

        coords = {}
        for lvl in sorted(by_level):
            row = by_level[lvl]
            row_total = len(row) * BOX_W + (len(row) - 1) * HGAP
            # Center row inside the screen-column area, after the open-URL gutter.
            x_start = PAD + EXTRA_LEFT + (screen_area_w - row_total) // 2
            for i, sid in enumerate(row):
                x = x_start + i * (BOX_W + HGAP)
                y = PAD + lvl * (BOX_H + VGAP)
                coords[sid] = (x, y)

        parts = [
            '<div style="overflow:auto;max-width:100%;">',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" '
            f'height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" '
            f'style="background:#f8f9fa;border-radius:6px;display:block;">',
            '<defs>',
            '<marker id="wa_arrow_nav" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#4a6cf7"/></marker>',
            '<marker id="wa_arrow_end" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#28a745"/></marker>',
            '<marker id="wa_arrow_url" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#6c757d"/></marker>',
            '</defs>',
        ]

        # Edges first so nodes sit on top.
        for src, es in edges.items():
            if src not in coords:
                continue
            sx, sy = coords[src]
            for e in es:
                if e['to'] not in coords:
                    continue
                tx, ty = coords[e['to']]
                x1, y1 = sx + BOX_W // 2, sy + BOX_H
                x2, y2 = tx + BOX_W // 2, ty
                parts.append(
                    f'<path d="M {x1} {y1} C {x1} {y1+40}, {x2} {y2-40}, '
                    f'{x2} {y2}" stroke="#4a6cf7" fill="none" '
                    f'stroke-width="1.5" marker-end="url(#wa_arrow_nav)"/>'
                )
                mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
                label = escape(e['label'])
                parts.append(
                    f'<rect x="{mid_x - 50}" y="{mid_y - 10}" width="100" '
                    f'height="20" fill="#ffffff" stroke="#4a6cf7" '
                    f'stroke-width="1" rx="10"/>'
                )
                parts.append(
                    f'<text x="{mid_x}" y="{mid_y + 4}" font-size="11" '
                    f'text-anchor="middle" fill="#4a6cf7" '
                    f'font-family="sans-serif">{label}</text>'
                )

        # "Complete" end-pills hanging directly below the source screen so
        # they stay inside the column and don't overflow the canvas.
        end_offsets = {}
        for src, label in completes:
            if src not in coords:
                continue
            sx, sy = coords[src]
            idx = end_offsets.get(src, 0)
            end_offsets[src] = idx + 1
            pill_w = 110
            ex = sx + (BOX_W - pill_w) // 2 + idx * (pill_w + 8)
            ey = sy + BOX_H + 24
            mid_x = sx + BOX_W // 2
            parts.append(
                f'<path d="M {mid_x} {sy + BOX_H} '
                f'L {mid_x} {ey}" stroke="#28a745" fill="none" '
                f'stroke-width="1.5" stroke-dasharray="4,3" '
                f'marker-end="url(#wa_arrow_end)"/>'
            )
            parts.append(
                f'<rect x="{ex}" y="{ey}" width="{pill_w}" height="28" '
                f'rx="14" fill="#d4edda" stroke="#28a745"/>'
            )
            parts.append(
                f'<text x="{ex + pill_w // 2}" y="{ey + 18}" font-size="11" '
                f'text-anchor="middle" fill="#155724" '
                f'font-family="sans-serif">✓ {escape(label)}</text>'
            )

        # External URL hops as muted cards in the left gutter.
        url_offsets = {}
        for src, url, label in external:
            if src not in coords:
                continue
            sx, sy = coords[src]
            idx = url_offsets.get(src, 0)
            url_offsets[src] = idx + 1
            card_w = 150
            ex = PAD + idx * 12   # tucked into the left gutter
            ey = sy + BOX_H // 2 - 17 + idx * 8
            parts.append(
                f'<path d="M {ex + card_w} {ey + 17} L {sx} '
                f'{sy + BOX_H // 2}" stroke="#6c757d" fill="none" '
                f'stroke-width="1.5" stroke-dasharray="4,3" '
                f'marker-end="url(#wa_arrow_url)"/>'
            )
            parts.append(
                f'<rect x="{ex}" y="{ey}" width="{card_w}" height="34" rx="6" '
                f'fill="#e9ecef" stroke="#6c757d"/>'
            )
            parts.append(
                f'<text x="{ex + card_w // 2}" y="{ey + 14}" font-size="10" '
                f'text-anchor="middle" fill="#495057" '
                f'font-family="sans-serif">↗ {escape(label)}</text>'
            )
            parts.append(
                f'<text x="{ex + card_w // 2}" y="{ey + 27}" font-size="9" '
                f'text-anchor="middle" fill="#6c757d" '
                f'font-family="monospace">{escape(url)}</text>'
            )

        # Nodes.
        for sid, (x, y) in coords.items():
            s = by_id[sid]
            if s.success:
                fill, stroke, badge_fill = '#d4edda', '#28a745', '#28a745'
                badge_text = '✓ success'
            elif s.terminal:
                fill, stroke, badge_fill = '#fff3cd', '#ffc107', '#ff8800'
                badge_text = 'terminal'
            elif sid == first:
                fill, stroke, badge_fill = '#cce5ff', '#0d6efd', '#0d6efd'
                badge_text = 'entry'
            else:
                fill, stroke, badge_fill = '#ffffff', '#adb5bd', '#6c757d'
                badge_text = ''

            parts.append(
                f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" '
                f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{x + 12}" y="{y + 22}" font-size="12" '
                f'font-weight="bold" fill="#212529" '
                f'font-family="monospace">{escape(sid)}</text>'
            )
            parts.append(
                f'<text x="{x + 12}" y="{y + 42}" font-size="12" '
                f'fill="#495057" font-family="sans-serif">'
                f'{escape((s.title or "")[:30])}</text>'
            )
            parts.append(
                f'<text x="{x + 12}" y="{y + 78}" font-size="10" '
                f'fill="#6c757d" font-family="sans-serif">'
                f'{s.component_count} component'
                f'{"s" if s.component_count != 1 else ""}</text>'
            )
            if badge_text:
                bw = 8 * len(badge_text) + 16
                parts.append(
                    f'<rect x="{x + BOX_W - bw - 8}" y="{y + 8}" '
                    f'width="{bw}" height="18" rx="9" fill="{badge_fill}"/>'
                )
                parts.append(
                    f'<text x="{x + BOX_W - bw // 2 - 8}" y="{y + 21}" '
                    f'font-size="10" text-anchor="middle" fill="#ffffff" '
                    f'font-family="sans-serif">{badge_text}</text>'
                )

        parts.append('</svg>')
        parts.append('</div>')
        return ''.join(parts)

    # ── JSON generator ──────────────────────────────────────────────────

    def write(self, vals):
        # When in structured mode, regenerate flow_json after any change.
        res = super().write(vals)
        for rec in self:
            if not rec.use_raw_json:
                generated = rec._generate_flow_json()
                if generated != rec.flow_json:
                    super(WhatsAppFlow, rec).write({'flow_json': generated})
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.use_raw_json:
                generated = rec._generate_flow_json()
                if generated != rec.flow_json:
                    super(WhatsAppFlow, rec).write({'flow_json': generated})
        return records

    def _generate_flow_json(self):
        """Build canonical Flow JSON v7.x from the structured records.
        Returns a JSON string ready to ship to Meta.
        """
        self.ensure_one()
        if not self.screen_ids:
            return json.dumps({"version": self.flow_version or "7.0", "screens": []}, indent=2)

        # Build the routing model by scanning every Footer/EmbeddedLink's
        # navigate action. Meta expects:
        #   {"WELCOME": ["DETAILS"], "DETAILS": ["THANK_YOU"], "THANK_YOU": []}
        routing = {}
        screens_json = []
        for screen in self.screen_ids.sorted(key=lambda s: (s.sequence, s.id)):
            sid = (screen.screen_id or '').strip()
            if not sid:
                continue
            targets = set()
            children = []
            for comp in screen.component_ids.sorted(key=lambda c: (c.sequence, c.id)):
                rendered = comp._render_flow_json()
                if rendered is None:
                    continue
                children.append(rendered)
                if comp.component_type in ('Footer', 'EmbeddedLink') and \
                        comp.action_type == 'navigate' and comp.target_screen_id:
                    targets.add(comp.target_screen_id.screen_id)
            routing[sid] = sorted(targets)

            screen_node = {
                "id": sid,
                "title": screen.title or sid,
                "layout": {
                    "type": screen.layout_type or 'SingleColumnLayout',
                    "children": children,
                },
            }
            if screen.terminal:
                screen_node["terminal"] = True
            if screen.success:
                screen_node["success"] = True
            if screen.data_schema and screen.data_schema.strip():
                try:
                    screen_node["data"] = json.loads(screen.data_schema)
                except (json.JSONDecodeError, ValueError):
                    pass  # validator will flag it
            screens_json.append(screen_node)

        out = {
            "version": self.flow_version or "7.0",
            "screens": screens_json,
        }
        # routing_model is optional but recommended; only include when there's
        # at least one navigation edge.
        if any(targets for targets in routing.values()):
            out["routing_model"] = routing
        return json.dumps(out, indent=2)

    # ── Validator ───────────────────────────────────────────────────────

    def _validate_structured(self):
        """Return a list of {level, where, message} dicts the form view
        renders into the Validation tab."""
        self.ensure_one()
        issues = []

        if not self.screen_ids:
            issues.append({
                'level': 'error', 'where': 'Flow',
                'message': "A flow needs at least one screen.",
            })
            return issues

        terminal_screens = self.screen_ids.filtered(lambda s: s.terminal)
        if not terminal_screens:
            issues.append({
                'level': 'error', 'where': 'Flow',
                'message': "At least one screen must be marked Terminal. "
                           "Otherwise the user has no way to complete the flow.",
            })
        elif len(terminal_screens) > 1:
            issues.append({
                'level': 'warning', 'where': 'Flow',
                'message': f"{len(terminal_screens)} screens are marked Terminal. "
                           "Meta accepts multiple, but usually only one is needed.",
            })

        all_screen_ids = {s.screen_id for s in self.screen_ids if s.screen_id}

        for screen in self.screen_ids:
            where = f"Screen '{screen.screen_id or '?'}'"

            # Component IDs unique within screen
            input_names = {}
            for comp in screen.component_ids:
                if comp.is_input and comp.name:
                    input_names.setdefault(comp.name, []).append(comp)
            for name, comps in input_names.items():
                if len(comps) > 1:
                    issues.append({
                        'level': 'error', 'where': where,
                        'message': f"Multiple input components share the name '{name}'. "
                                   "Each input on a screen needs a unique name.",
                    })

            for comp in screen.component_ids:
                cwhere = f"{where} · {comp.component_type}"

                # Inputs need a name + label
                if comp.is_input:
                    if not comp.name:
                        issues.append({
                            'level': 'error', 'where': cwhere,
                            'message': "Input components need a Field Name.",
                        })
                    if not comp.label:
                        issues.append({
                            'level': 'warning', 'where': cwhere,
                            'message': "Input components should have a Label "
                                       "so the user knows what to enter.",
                        })

                # Choice components need options
                if comp.is_choice and not comp.option_ids:
                    issues.append({
                        'level': 'error', 'where': cwhere,
                        'message': "Choice components need at least one option.",
                    })

                # Footer / EmbeddedLink / OptIn need an action
                if comp.is_action and not comp.action_type:
                    issues.append({
                        'level': 'error', 'where': cwhere,
                        'message': "Action components need an Action Type.",
                    })

                # navigate action must point at an existing screen
                if comp.action_type == 'navigate':
                    if not comp.target_screen_id:
                        issues.append({
                            'level': 'error', 'where': cwhere,
                            'message': "Navigate action is missing a target screen.",
                        })
                    elif comp.target_screen_id.screen_id not in all_screen_ids:
                        issues.append({
                            'level': 'error', 'where': cwhere,
                            'message': f"Navigate target '{comp.target_screen_id.screen_id}' "
                                       "doesn't exist on this flow.",
                        })
                if comp.action_type == 'open_url' and not comp.open_url:
                    issues.append({
                        'level': 'error', 'where': cwhere,
                        'message': "Open URL action needs a URL.",
                    })

                # Image needs a source
                if comp.component_type == 'Image' and not comp.image_src:
                    issues.append({
                        'level': 'error', 'where': cwhere,
                        'message': "Image components need an Image Source.",
                    })

                # Text-display components need text
                if comp.component_type in ('TextHeading', 'TextSubheading',
                                            'TextBody', 'TextCaption', 'RichText'):
                    if not (comp.text or comp.label):
                        issues.append({
                            'level': 'warning', 'where': cwhere,
                            'message': "Text component has no content.",
                        })

        return issues

    # ------------------------------------------------------------------
    # Starter templates — buttons on the empty-Screens alert. Each builder
    # populates *self* with screens/components/options for a common pattern,
    # then returns an action to reload the form so the author can tweak.
    # ------------------------------------------------------------------

    def _ensure_template_target_empty(self):
        """Templates overwrite the current flow's structured records. Guard
        against accidentally clobbering an existing flow."""
        self.ensure_one()
        if self.screen_ids:
            from odoo.exceptions import UserError
            raise UserError(
                "This flow already has screens — templates only apply to "
                "empty flows. Create a new flow first, or delete the existing "
                "screens.")

    def _reload_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.flow',
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_template_lead_capture(self):
        """Two-screen lead-capture: form on screen 1, thank-you on screen 2."""
        self._ensure_template_target_empty()
        Screen = self.env['whatsapp.flow.screen']
        Comp = self.env['whatsapp.flow.component']
        Opt = self.env['whatsapp.flow.component.option']

        welcome = Screen.create({
            'flow_id': self.id, 'screen_id': 'WELCOME',
            'title': 'Get in touch', 'sequence': 10,
        })
        Comp.create({'screen_id': welcome.id, 'component_type': 'TextHeading',
                     'text': 'Get in touch', 'sequence': 10})
        Comp.create({'screen_id': welcome.id, 'component_type': 'TextBody',
                     'text': "Tell us a bit about yourself and we'll be in touch.",
                     'sequence': 20})
        Comp.create({'screen_id': welcome.id, 'component_type': 'TextInput',
                     'name': 'full_name', 'label': 'Full name',
                     'required': True, 'sequence': 30})
        Comp.create({'screen_id': welcome.id, 'component_type': 'TextInput',
                     'name': 'email', 'label': 'Email',
                     'input_type': 'email', 'required': True, 'sequence': 40})
        Comp.create({'screen_id': welcome.id, 'component_type': 'TextInput',
                     'name': 'phone', 'label': 'Phone (optional)',
                     'input_type': 'phone', 'sequence': 50})
        interest = Comp.create({
            'screen_id': welcome.id, 'component_type': 'Dropdown',
            'name': 'interest', 'label': 'What are you interested in?',
            'required': True, 'sequence': 60,
        })
        for i, (oid, title) in enumerate([
            ('sales', 'Sales'),
            ('support', 'Support'),
            ('partnership', 'Partnership'),
            ('other', 'Other'),
        ], start=1):
            Opt.create({'component_id': interest.id, 'option_id': oid,
                        'title': title, 'sequence': i * 10})

        thanks = Screen.create({
            'flow_id': self.id, 'screen_id': 'THANKS',
            'title': 'Thank you', 'sequence': 20,
            'terminal': True, 'success': True,
        })
        Comp.create({'screen_id': welcome.id, 'component_type': 'Footer',
                     'label': 'Submit', 'sequence': 100,
                     'action_type': 'navigate', 'target_screen_id': thanks.id})
        Comp.create({'screen_id': thanks.id, 'component_type': 'TextHeading',
                     'text': 'Thank you!', 'sequence': 10})
        Comp.create({'screen_id': thanks.id, 'component_type': 'TextBody',
                     'text': "We've got your details. A team member will be in "
                             "touch within 24 hours.", 'sequence': 20})
        Comp.create({'screen_id': thanks.id, 'component_type': 'Footer',
                     'label': 'Done', 'sequence': 30, 'action_type': 'complete'})

        self.category = self.category or 'LEAD_GENERATION'
        return self._reload_self()

    def action_template_nps(self):
        """Two-screen NPS: score selector, then free-text feedback."""
        self._ensure_template_target_empty()
        Screen = self.env['whatsapp.flow.screen']
        Comp = self.env['whatsapp.flow.component']
        Opt = self.env['whatsapp.flow.component.option']

        score_screen = Screen.create({
            'flow_id': self.id, 'screen_id': 'SCORE',
            'title': 'How likely are you to recommend us?', 'sequence': 10,
        })
        Comp.create({'screen_id': score_screen.id, 'component_type': 'TextHeading',
                     'text': 'How likely are you to recommend us?', 'sequence': 10})
        Comp.create({'screen_id': score_screen.id, 'component_type': 'TextBody',
                     'text': '0 = Not at all likely, 10 = Extremely likely',
                     'sequence': 20})
        score = Comp.create({
            'screen_id': score_screen.id, 'component_type': 'RadioButtonsGroup',
            'name': 'score', 'label': 'Your score', 'required': True,
            'sequence': 30,
        })
        for i in range(0, 11):
            Opt.create({'component_id': score.id, 'option_id': str(i),
                        'title': str(i), 'sequence': (i + 1) * 10})

        feedback = Screen.create({
            'flow_id': self.id, 'screen_id': 'FEEDBACK',
            'title': 'Tell us more', 'sequence': 20,
            'terminal': True, 'success': True,
        })
        Comp.create({'screen_id': score_screen.id, 'component_type': 'Footer',
                     'label': 'Next', 'sequence': 100,
                     'action_type': 'navigate', 'target_screen_id': feedback.id})
        Comp.create({'screen_id': feedback.id, 'component_type': 'TextHeading',
                     'text': 'Tell us more (optional)', 'sequence': 10})
        Comp.create({'screen_id': feedback.id, 'component_type': 'TextArea',
                     'name': 'comment',
                     'label': "What's the main reason for your score?",
                     'sequence': 20})
        Comp.create({'screen_id': feedback.id, 'component_type': 'Footer',
                     'label': 'Submit feedback', 'sequence': 30,
                     'action_type': 'complete'})

        self.category = self.category or 'SURVEY'
        return self._reload_self()

    def action_template_appointment(self):
        """Three-screen booking: pick service, pick date+time, confirmation."""
        self._ensure_template_target_empty()
        Screen = self.env['whatsapp.flow.screen']
        Comp = self.env['whatsapp.flow.component']
        Opt = self.env['whatsapp.flow.component.option']

        service = Screen.create({
            'flow_id': self.id, 'screen_id': 'SERVICE',
            'title': 'Book an appointment', 'sequence': 10,
        })
        Comp.create({'screen_id': service.id, 'component_type': 'TextHeading',
                     'text': 'Book an appointment', 'sequence': 10})
        svc = Comp.create({
            'screen_id': service.id, 'component_type': 'Dropdown',
            'name': 'service', 'label': 'Service', 'required': True,
            'sequence': 20,
        })
        for i, (oid, title) in enumerate([
            ('consultation', 'Consultation'),
            ('follow_up', 'Follow-up'),
            ('initial_visit', 'Initial visit'),
        ], start=1):
            Opt.create({'component_id': svc.id, 'option_id': oid,
                        'title': title, 'sequence': i * 10})

        time_screen = Screen.create({
            'flow_id': self.id, 'screen_id': 'TIME',
            'title': 'Pick a date and time', 'sequence': 20,
        })
        Comp.create({'screen_id': service.id, 'component_type': 'Footer',
                     'label': 'Next', 'sequence': 100,
                     'action_type': 'navigate', 'target_screen_id': time_screen.id})

        Comp.create({'screen_id': time_screen.id, 'component_type': 'TextHeading',
                     'text': 'Pick a date and time', 'sequence': 10})
        Comp.create({'screen_id': time_screen.id, 'component_type': 'DatePicker',
                     'name': 'preferred_date', 'label': 'Preferred date',
                     'required': True, 'sequence': 20})
        tod = Comp.create({
            'screen_id': time_screen.id, 'component_type': 'Dropdown',
            'name': 'preferred_time', 'label': 'Time of day',
            'required': True, 'sequence': 30,
        })
        for i, (oid, title) in enumerate([
            ('morning', 'Morning (08:00 - 12:00)'),
            ('afternoon', 'Afternoon (12:00 - 17:00)'),
            ('evening', 'Evening (17:00 - 20:00)'),
        ], start=1):
            Opt.create({'component_id': tod.id, 'option_id': oid,
                        'title': title, 'sequence': i * 10})
        Comp.create({'screen_id': time_screen.id, 'component_type': 'TextArea',
                     'name': 'notes', 'label': 'Any notes for us?',
                     'sequence': 40})

        confirm = Screen.create({
            'flow_id': self.id, 'screen_id': 'CONFIRM',
            'title': 'Confirmation', 'sequence': 30,
            'terminal': True, 'success': True,
        })
        Comp.create({'screen_id': time_screen.id, 'component_type': 'Footer',
                     'label': 'Next', 'sequence': 100,
                     'action_type': 'navigate', 'target_screen_id': confirm.id})
        Comp.create({'screen_id': confirm.id, 'component_type': 'TextHeading',
                     'text': 'All set!', 'sequence': 10})
        Comp.create({'screen_id': confirm.id, 'component_type': 'TextBody',
                     'text': "We'll send you a confirmation message shortly. "
                             "Thanks for booking with us.", 'sequence': 20})
        Comp.create({'screen_id': confirm.id, 'component_type': 'Footer',
                     'label': 'Done', 'sequence': 30, 'action_type': 'complete'})

        self.category = self.category or 'APPOINTMENT_BOOKING'
        return self._reload_self()

    def action_create_flow_meta(self):
        """
        Create flow in Meta WhatsApp Business API.
        
        Based on: https://developers.facebook.com/docs/whatsapp/flows/gettingstarted
        """
        self.ensure_one()
        
        try:
            # Get access token and business account ID
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
            if not access_token:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token not configured. Please authenticate first.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            if not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Validate JSON
            try:
                flow_data = json.loads(self.flow_json)
            except json.JSONDecodeError as e:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Invalid JSON format: {str(e)}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Build payload
            payload = {
                'name': self.name,
                'categories': [self.category] if self.category else ['LEAD_GENERATION'],
                'endpoint_uri': '',  # Can be set for dynamic flows
                'json_flow': flow_data,
            }
            
            # API endpoint
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/flows"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            _logger.info(f"Creating flow {self.name} in Meta API")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code in (200, 201):
                response_data = response.json()
                flow_id = response_data.get('id')
                
                # Extract first page ID from flow JSON
                first_page_id = None
                try:
                    screens = flow_data.get('screens', [])
                    if screens:
                        first_page_id = screens[0].get('id')
                except:
                    pass
                
                self.write({
                    'flow_id_meta': flow_id,
                    'status': 'DRAFT',
                    'first_page_id': first_page_id,
                })
                
                _logger.info(f"Flow created successfully. Flow ID: {flow_id}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': f'Flow created successfully! Flow ID: {flow_id}. Status: DRAFT. Publish it to use in templates.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                
                _logger.error(f"Failed to create flow: {response.status_code} - {error_message}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to create flow: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error creating flow: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error creating flow: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_publish_flow(self):
        """
        Publish flow in Meta API.
        Only published flows can be used in approved templates.
        
        Before publishing, the flow is updated with the latest JSON to ensure
        it's valid and in sync with Meta's servers.
        """
        self.ensure_one()
        
        if not self.flow_id_meta:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Flow must be created in Meta first before publishing.',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
            if not access_token or not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token or Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Validate JSON first
            try:
                flow_data = json.loads(self.flow_json)
            except json.JSONDecodeError as e:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Invalid flow JSON format: {str(e)}. Please fix the JSON before publishing.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Basic validation of flow structure
            validation_errors = []
            if 'version' not in flow_data:
                validation_errors.append("Missing required field: 'version'")
            if 'screens' not in flow_data:
                validation_errors.append("Missing required field: 'screens'")
            elif not isinstance(flow_data.get('screens'), list) or len(flow_data.get('screens', [])) == 0:
                validation_errors.append("'screens' must be a non-empty array")
            else:
                # Validate each screen has required fields
                for idx, screen in enumerate(flow_data.get('screens', [])):
                    if 'id' not in screen:
                        validation_errors.append(f"Screen {idx} is missing required field: 'id'")
                    if 'layout' not in screen:
                        validation_errors.append(f"Screen {idx} is missing required field: 'layout'")
            
            if validation_errors:
                error_msg = "Flow JSON validation errors:\n" + "\n".join(f"- {err}" for err in validation_errors)
                _logger.error(f"Flow JSON validation failed: {error_msg}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Validation Error',
                        'message': error_msg,
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Check current flow status from Meta before attempting to publish
            # This helps identify if the flow is in the correct state
            check_url = f"https://graph.facebook.com/v18.0/{self.flow_id_meta}?fields=id,name,status,version"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            _logger.info(f"Checking flow {self.flow_id_meta} status before publishing")
            check_response = requests.get(check_url, headers=headers, timeout=30)
            
            if check_response.status_code == 200:
                flow_info = check_response.json()
                current_status = flow_info.get('status', 'UNKNOWN')
                _logger.info(f"Flow current status: {current_status}")
                
                if current_status not in ('DRAFT', 'UNKNOWN'):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Error',
                            'message': f'Flow is in {current_status} status. Only DRAFT flows can be published. Please create a new version or reset the flow to DRAFT status.',
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
            else:
                _logger.warning(f"Could not check flow status: {check_response.status_code}")
            
            # Prepare headers for API calls
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            flow_url = f"https://graph.facebook.com/v18.0/{self.flow_id_meta}"
            
            # Filter flow_data to only include fields allowed in json_flow
            # According to Meta API, json_flow should only contain version and screens
            # Remove routing_model, data_api_version, and other metadata fields
            filtered_flow_data = {
                'version': flow_data.get('version'),
                'screens': flow_data.get('screens', []),
            }
            
            # Update and publish in one request
            # According to Meta docs, we can include both json_flow and status in the same request
            _logger.info(f"Updating and publishing flow {self.flow_id_meta}")
            
            publish_payload = {
                'json_flow': filtered_flow_data,
                'status': 'PUBLISHED',
            }
            
            # Add name and category if specified
            if self.name:
                publish_payload['name'] = self.name
            if self.category:
                publish_payload['categories'] = [self.category]
            
            _logger.debug(f"Publish URL: {flow_url}")
            _logger.debug(f"Publish payload keys: {list(publish_payload.keys())}")
            _logger.debug(f"Filtered flow data keys: {list(filtered_flow_data.keys())}")
            _logger.debug(f"Number of screens: {len(filtered_flow_data.get('screens', []))}")
            response = requests.post(flow_url, headers=headers, json=publish_payload, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                self.write({'status': 'PUBLISHED'})
                _logger.info(f"Flow published successfully. Response: {response_data}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': 'Flow published successfully! It can now be used in approved templates.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_info = error_data.get('error', {})
                error_message = error_info.get('message', response.text)
                error_code = error_info.get('code', 'Unknown')
                error_subcode = error_info.get('error_subcode', '')
                error_data_details = error_info.get('error_data', {})
                error_user_title = error_info.get('error_user_title', '')
                error_user_msg = error_info.get('error_user_msg', '')
                
                _logger.error(f"Failed to publish flow: {response.status_code} - {error_message} (Code: {error_code}, Subcode: {error_subcode})")
                _logger.error(f"Full error response: {json.dumps(error_data, indent=2)}")
                
                # Log the raw response for debugging
                _logger.error(f"Raw response text: {response.text}")
                
                # Provide more helpful error message based on error code and subcode
                if error_code == 100:
                    if error_subcode == 4233023:
                        detailed_msg = (
                            f"Invalid parameter error. Common causes:\n"
                            f"1. Flow JSON has validation errors - check all required fields are present\n"
                            f"2. Business account is not fully verified in Meta Business Manager\n"
                            f"3. Phone number display name is not approved\n"
                            f"4. Flow contains unsupported components or invalid values\n\n"
                            f"Error details: {error_message}"
                        )
                    else:
                        detailed_msg = f"Validation error: {error_message}. Ensure flow is in DRAFT status and has no validation errors."
                    
                    # Add error_data details if available
                    if error_data_details:
                        detailed_msg += f"\n\nAdditional details: {json.dumps(error_data_details, indent=2)}"
                elif 'parameter' in error_message.lower():
                    detailed_msg = f"Invalid parameter: {error_message}. Check that flow JSON is valid and all required fields are present."
                elif 'integrity' in error_message.lower() or 'verification' in error_message.lower():
                    detailed_msg = (
                        f"Integrity/Verification error: {error_message}\n\n"
                        f"Please ensure:\n"
                        f"1. Your WhatsApp Business Account is fully verified in Meta Business Manager\n"
                        f"2. Your phone number's display name is approved\n"
                        f"3. Your business verification is complete"
                    )
                else:
                    detailed_msg = f"{error_message} (Error Code: {error_code})"
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to publish flow: {detailed_msg}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"Error publishing flow: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error publishing flow: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _get_flow_details(self, flow_id):
        """
        Get flow details from Meta API.
        """
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                      IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
        
        if not access_token:
            raise ValueError('Access token not configured')
        
        url = f"https://graph.facebook.com/v18.0/{flow_id}?fields=id,name,categories,preview,status,validation_errors,json_version,data_api_version,endpoint_uri"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_flow_assets(self, flow_id):
        """
        Get flow assets from Meta API.
        """
        IrConfigParameter = self.env['ir.config_parameter'].sudo()
        access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                      IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
        
        if not access_token:
            raise ValueError('Access token not configured')
        
        url = f"https://graph.facebook.com/v18.0/{flow_id}/assets"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_flow_json(self, download_url):
        """
        Download flow JSON from the provided URL.
        """
        try:
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error fetching flow JSON from {download_url}: {e}")
            raise
    
    def action_fetch_from_meta(self):
        """
        Fetch flows from Meta API and sync with local records.
        This method fetches the flow JSON from Meta's assets API.
        """
        try:
            IrConfigParameter = self.env['ir.config_parameter'].sudo()
            access_token = IrConfigParameter.get_param('comm_whatsapp.access_token') or \
                          IrConfigParameter.get_param('comm_whatsapp.long_lived_token')
            business_account_id = IrConfigParameter.get_param('comm_whatsapp.business_account_id')
            
            if not access_token or not business_account_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Access token or Business Account ID not configured.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            # Fetch flows from Meta
            url = f"https://graph.facebook.com/v18.0/{business_account_id}/flows"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                flows = data.get('data', [])
                
                created_count = 0
                updated_count = 0
                error_count = 0
                error_messages = []
                
                for flow_data in flows:
                    try:
                        flow_id = flow_data.get('id')
                        name = flow_data.get('name')
                        status = flow_data.get('status')
                        
                        # Find or create flow
                        flow = self.search([('flow_id_meta', '=', flow_id)], limit=1)
                        
                        # Get flow details (includes json_version, preview, etc.)
                        flow_details = self._get_flow_details(flow_id)
                        _logger.info(f"Flow details for {flow_id}: {flow_details}")
                        
                        # Get flow assets to find the JSON download URL
                        flow_assets = self._get_flow_assets(flow_id)
                        _logger.info(f"Flow assets for {flow_id}: {flow_assets}")
                        
                        # Find the FLOW_JSON asset
                        json_asset = None
                        if flow_assets.get('data'):
                            json_assets = [asset for asset in flow_assets['data'] if asset.get('asset_type') == 'FLOW_JSON']
                            if json_assets:
                                json_asset = json_assets[0]
                        
                        # Download the flow JSON
                        flow_json = None
                        if json_asset and json_asset.get('download_url'):
                            flow_json = self._get_flow_json(json_asset['download_url'])
                            _logger.info(f"Downloaded flow JSON for {flow_id}")
                        else:
                            _logger.warning(f"No FLOW_JSON asset found for flow {flow_id}")
                        
                        # Prepare values
                        vals = {
                            'flow_id_meta': flow_id,
                            'status': status,
                            'version': flow_details.get('json_version'),
                            'category': flow_data.get('categories', [None])[0] if flow_data.get('categories') else None,
                        }
                        
                        # Add flow JSON if we got it
                        if flow_json:
                            # Extract first page ID from screens
                            first_page_id = None
                            screens = flow_json.get('screens', [])
                            if screens:
                                first_page_id = screens[0].get('id')
                            
                            vals.update({
                                'flow_json': json.dumps(flow_json, indent=2),
                                'first_page_id': first_page_id,
                            })
                        
                        # Handle preview URL and expiry
                        preview = flow_details.get('preview', {})
                        if preview:
                            preview_url = preview.get('preview_url')
                            expires_at = preview.get('expires_at')
                            if preview_url:
                                vals['preview_url'] = preview_url
                            if expires_at:
                                try:
                                    from datetime import datetime
                                    expiry_datetime = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M:%S%z')
                                    vals['preview_url_expiry_date'] = expiry_datetime.strftime('%Y-%m-%d %H:%M:%S')
                                except Exception as e:
                                    _logger.warning(f"Could not parse expiry date {expires_at}: {e}")
                        
                        if flow:
                            # Update existing flow
                            flow.write(vals)
                            updated_count += 1
                            _logger.info(f"Updated flow {flow_id}: {name}")
                        else:
                            # Create new flow
                            if not name:
                                name = flow_id  # Fallback name
                            vals['name'] = name
                            self.create(vals)
                            created_count += 1
                            _logger.info(f"Created flow {flow_id}: {name}")
                    
                    except Exception as e:
                        error_count += 1
                        error_msg = f"Error syncing flow {flow_data.get('id', 'unknown')}: {str(e)}"
                        error_messages.append(error_msg)
                        _logger.error(error_msg, exc_info=True)
                
                # Build success message
                message = f'Synced flows: {created_count} created, {updated_count} updated.'
                if error_count > 0:
                    message += f' {error_count} errors occurred.'
                    if error_messages:
                        message += '\n\nErrors:\n' + '\n'.join(error_messages[:5])  # Show first 5 errors
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success' if error_count == 0 else 'Partial Success',
                        'message': message,
                        'type': 'success' if error_count == 0 else 'warning',
                        'sticky': error_count > 0,
                    }
                }
            else:
                error_data = response.json() if response.text else {}
                error_message = error_data.get('error', {}).get('message', response.text)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': f'Failed to fetch flows: {error_message}',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
        except Exception as e:
            _logger.error(f"Error in action_fetch_from_meta: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Failed to sync flows: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }
                
        except Exception as e:
            _logger.error(f"Error fetching flows: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error fetching flows: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

