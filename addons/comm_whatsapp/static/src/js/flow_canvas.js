/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const TYPE_CFG = {
    TextHeading:        { icon: "🅰️", label: "Heading",  color: "#1f2937", bg: "#f3f4f6", border: "#d1d5db" },
    TextSubheading:     { icon: "🔠", label: "Subheading", color: "#374151", bg: "#f3f4f6", border: "#d1d5db" },
    TextBody:           { icon: "📝", label: "Body Text",  color: "#374151", bg: "#f9fafb", border: "#e5e7eb" },
    TextCaption:        { icon: "🏷️", label: "Caption",    color: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" },
    RichText:           { icon: "📄", label: "Rich Text",  color: "#374151", bg: "#f9fafb", border: "#e5e7eb" },
    Image:              { icon: "🖼️", label: "Image",      color: "#b45309", bg: "#fffbeb", border: "#fcd34d" },
    TextInput:          { icon: "✏️", label: "Input",       color: "#7c3aed", bg: "#f5f3ff", border: "#c4b5fd" },
    TextArea:           { icon: "📔", label: "Text Area",   color: "#7c3aed", bg: "#f5f3ff", border: "#c4b5fd" },
    Dropdown:           { icon: "📜", label: "Dropdown",    color: "#0891b2", bg: "#ecfeff", border: "#67e8f9" },
    RadioButtonsGroup:  { icon: "🔘", label: "Radio",       color: "#0891b2", bg: "#ecfeff", border: "#67e8f9" },
    CheckboxGroup:      { icon: "☑️", label: "Checkboxes",  color: "#0891b2", bg: "#ecfeff", border: "#67e8f9" },
    DatePicker:         { icon: "📅", label: "Date Picker", color: "#be185d", bg: "#fdf2f8", border: "#f9a8d4" },
    CalendarPicker:     { icon: "🗓️", label: "Calendar",    color: "#be185d", bg: "#fdf2f8", border: "#f9a8d4" },
    OptIn:              { icon: "✔️", label: "Opt-In",      color: "#0891b2", bg: "#ecfeff", border: "#67e8f9" },
    PhotoPicker:        { icon: "📷", label: "Photo",       color: "#b45309", bg: "#fffbeb", border: "#fcd34d" },
    DocumentPicker:     { icon: "📁", label: "Document",    color: "#475569", bg: "#f8fafc", border: "#cbd5e1" },
    EmbeddedLink:       { icon: "🔗", label: "Link",        color: "#1a73e8", bg: "#e8f0fe", border: "#93c5fd" },
    Footer:             { icon: "🟢", label: "Footer CTA",  color: "#16a34a", bg: "#f0fdf4", border: "#86efac" },
};
const SCREEN_CFG_DEFAULT  = { color: "#4338ca", bg: "#eef2ff", border: "#a5b4fc" };
const SCREEN_CFG_ENTRY    = { color: "#1d4ed8", bg: "#dbeafe", border: "#60a5fa" };
const SCREEN_CFG_TERMINAL = { color: "#92400e", bg: "#fef3c7", border: "#fcd34d" };
const SCREEN_CFG_SUCCESS  = { color: "#065f46", bg: "#d1fae5", border: "#6ee7b7" };

function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}


export class FlowCanvasAction extends Component {
    static template = "comm_whatsapp.FlowCanvasAction";
    static props = ["action", "actionId?"];

    setup() {
        this.orm     = useService("orm");
        this.action  = useService("action");
        this.notif   = useService("notification");
        this.dialog  = useService("dialog");
        this.flowId  = this.props.action.params?.flow_id;
        this.canvasRef = useRef("canvas");

        this.state = useState({
            loading:      true,
            flowName:     this.props.action.params?.flow_name || "",
            screens:      [],   // [{id, screen_id, title, terminal, success, sequence, components:[...], navTargets:[id,...]}]
            screensById:  {},
            entryScreenId: null,
            selectedScreenId: null,
            panelVisible: true,
            panelMode:    "props",  // "props" | "preview"
            zoom:         1,
            // Interactive preview session — per-screen form values keyed by
            // component name. Resets when the preview restarts. The walker
            // tracks where we are; complete/open_url surface as overlays.
            preview: {
                currentScreenId: null,
                values:          {},     // { "first_name": "...", ... }
                history:         [],     // stack of visited screen ids
                ended:           false,
                endKind:         null,   // "complete" | "open_url" | "terminal"
                endMessage:      "",
            },
        });

        this._drawLinesFn = null;
        this._relayoutRowsFn = null;
        this._onResize    = () => {
            this._relayoutRowsFn?.();
            this._drawLinesFn?.();
        };
        this._canvasClickFn = (ev) => {
            if (ev.target.closest(".o_flow_card")) return;
            this.state.selectedScreenId = null;
            // Same visual-swap trick as _selectScreen — avoid a full re-render.
            const grid = this.canvasRef.el?.querySelector(".o_flow_grid");
            grid?.querySelectorAll(".o_flow_card.o_flow_card_selected")
                .forEach(c => c.classList.remove("o_flow_card_selected"));
        };

        // Canvas re-renders are expensive (rip out every card, rebuild the
        // DOM, redraw the SVG). Keeping the render tied to onPatched meant
        // every unrelated state change — most notably a user typing into a
        // preview input — nuked and rebuilt the whole canvas each keystroke.
        // Version-guard it: bump _canvasDataVersion when flow structure
        // changes; only re-render when the rendered version is stale.
        this._canvasDataVersion = 0;
        this._renderedCanvasVersion = -1;

        onMounted(async () => {
            await this._loadData();
            window.addEventListener("resize", this._onResize, { passive: true });
        });
        onPatched(() => {
            if (this.state.loading || !this.canvasRef.el) return;
            if (this._renderedCanvasVersion === this._canvasDataVersion) return;
            this._renderedCanvasVersion = this._canvasDataVersion;
            this._renderCanvas();
        });
        onWillUnmount(() => window.removeEventListener("resize", this._onResize));
    }

    // ── Data ────────────────────────────────────────────────────────────

    async _loadData() {
        this.state.loading = true;

        // Pull flow name in case it wasn't in the params.
        if (!this.state.flowName) {
            const flow = await this.orm.read("whatsapp.flow", [this.flowId], ["name"]);
            this.state.flowName = flow[0]?.name || "";
        }

        const screens = await this.orm.searchRead(
            "whatsapp.flow.screen",
            [["flow_id", "=", this.flowId]],
            ["id", "screen_id", "title", "terminal", "success", "sequence", "component_ids"],
            { order: "sequence, id" }
        );

        const compIds = screens.flatMap(s => s.component_ids);
        const comps = compIds.length ? await this.orm.read(
            "whatsapp.flow.component", compIds,
            ["id", "screen_id", "component_type", "name", "label", "text",
             "required", "sequence", "action_type", "target_screen_id",
             "open_url", "input_type", "init_value", "image_src", "option_ids"]
        ) : [];

        const optIds = comps.flatMap(c => c.option_ids);
        const opts = optIds.length ? await this.orm.read(
            "whatsapp.flow.component.option", optIds,
            ["id", "title", "sequence"]
        ) : [];
        const optById = Object.fromEntries(opts.map(o => [o.id, o]));

        const compById = Object.fromEntries(comps.map(c => {
            c.options = c.option_ids.map(id => optById[id]).filter(Boolean)
                .sort((a, b) => a.sequence - b.sequence);
            return [c.id, c];
        }));

        const screensById = {};
        const screensList = screens.map(s => {
            const sc = {
                id:        s.id,
                screen_id: s.screen_id,
                title:     s.title,
                terminal:  s.terminal,
                success:   s.success,
                sequence:  s.sequence,
                components: s.component_ids
                    .map(id => compById[id])
                    .filter(Boolean)
                    .sort((a, b) => a.sequence - b.sequence),
            };
            sc.navTargets = sc.components
                .filter(c => c.action_type === "navigate" && Array.isArray(c.target_screen_id))
                .map(c => ({ id: c.target_screen_id[0], label: c.label || "navigate" }));
            sc.completes = sc.components
                .filter(c => c.action_type === "complete")
                .map(c => c.label || "complete");
            sc.openUrls  = sc.components
                .filter(c => c.action_type === "open_url" && c.open_url)
                .map(c => ({ url: c.open_url, label: c.label || "open URL" }));
            screensById[s.id] = sc;
            return sc;
        });

        this.state.screens     = screensList;
        this.state.screensById = screensById;
        this.state.entryScreenId = screensList[0]?.id || null;
        if (!this.state.selectedScreenId && screensList.length) {
            this.state.selectedScreenId = screensList[0].id;
        }
        this.state.loading = false;
        this._canvasDataVersion++;
    }

    get selectedScreen() {
        return this.state.screensById[this.state.selectedScreenId] || null;
    }
    get zoomLabel() {
        return Math.round(this.state.zoom * 100) + "%";
    }

    // ── Toolbar actions ─────────────────────────────────────────────────

    _setZoom(z) {
        this.state.zoom = Math.min(2, Math.max(0.5, +z.toFixed(2)));
    }
    _togglePanel() {
        this.state.panelVisible = !this.state.panelVisible;
        // Resize the canvas after the transition finishes so connector lines reflow.
        setTimeout(() => this._drawLinesFn?.(), 280);
    }
    _setPanelMode(mode) {
        this.state.panelMode = mode;
        // First time the user opens Preview, anchor it at the entry screen.
        if (mode === "preview" && !this.state.preview.currentScreenId) {
            this._previewReset();
        }
    }

    // ── Interactive preview ─────────────────────────────────────────────

    get previewScreen() {
        return this.state.screensById[this.state.preview.currentScreenId] || null;
    }
    _previewReset() {
        this.state.preview.currentScreenId = this.state.entryScreenId;
        this.state.preview.values  = {};
        this.state.preview.history = [];
        this.state.preview.ended      = false;
        this.state.preview.endKind    = null;
        this.state.preview.endMessage = "";
    }
    _previewSetValue(name, value) {
        if (!name) return;
        this.state.preview.values[name] = value;
    }
    _previewToggleCheck(name, optionId) {
        if (!name) return;
        const cur = Array.isArray(this.state.preview.values[name])
            ? [...this.state.preview.values[name]] : [];
        const ix = cur.indexOf(optionId);
        if (ix >= 0) cur.splice(ix, 1);
        else cur.push(optionId);
        this.state.preview.values[name] = cur;
    }
    _previewChecked(name, optionId) {
        const cur = this.state.preview.values[name];
        return Array.isArray(cur) && cur.includes(optionId);
    }
    _previewActOnFooter(c) {
        // Capture-and-route: persist the form values, then act on the Footer.
        if (c.action_type === "navigate" && Array.isArray(c.target_screen_id)) {
            const tgt = c.target_screen_id[0];
            if (!this.state.screensById[tgt]) {
                this.notif.add("Navigate target is missing from this flow.",
                               { type: "danger" });
                return;
            }
            this.state.preview.history.push(this.state.preview.currentScreenId);
            this.state.preview.currentScreenId = tgt;
            // Auto-focus on the new screen on the canvas so the two views stay in sync.
            this.state.selectedScreenId = tgt;
            return;
        }
        if (c.action_type === "complete") {
            this.state.preview.ended = true;
            this.state.preview.endKind = "complete";
            this.state.preview.endMessage = "Flow completed — values would be sent back to the business.";
            return;
        }
        if (c.action_type === "open_url") {
            this.state.preview.ended = true;
            this.state.preview.endKind = "open_url";
            this.state.preview.endMessage = `Would open URL: ${c.open_url || "(not set)"}`;
            return;
        }
        // No action set: terminate the walk.
        this.state.preview.ended = true;
        this.state.preview.endKind = "terminal";
        this.state.preview.endMessage = "Footer has no action configured.";
    }
    _previewBack() {
        if (this.state.preview.ended) {
            this.state.preview.ended = false;
            this.state.preview.endKind = null;
            this.state.preview.endMessage = "";
            return;
        }
        const prev = this.state.preview.history.pop();
        if (prev) {
            this.state.preview.currentScreenId = prev;
            this.state.selectedScreenId = prev;
        }
    }
    async _goBack() {
        await this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "whatsapp.flow",
            res_id:    this.flowId,
            views:     [[false, "form"]],
            target:    "current",
        });
    }
    async _editFlow() {
        await this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "whatsapp.flow",
            res_id:    this.flowId,
            views:     [[false, "form"]],
            target:    "current",
        });
    }
    async _editScreen(screenId) {
        this.dialog.add(FormViewDialog, {
            resModel: "whatsapp.flow.screen",
            resId:    screenId,
            title:    "Edit Screen",
            onRecordSaved: async () => { await this._loadData(); },
        });
    }
    async _addScreen() {
        this.dialog.add(FormViewDialog, {
            resModel: "whatsapp.flow.screen",
            context:  { default_flow_id: this.flowId },
            title:    "Add Screen",
            onRecordSaved: async (rec) => {
                await this._loadData();
                if (rec?.resId) this.state.selectedScreenId = rec.resId;
            },
        });
    }
    async _addComponent(screenId) {
        this.dialog.add(FormViewDialog, {
            resModel: "whatsapp.flow.component",
            context:  { default_screen_id: screenId },
            title:    "Add Component",
            onRecordSaved: async () => { await this._loadData(); },
        });
    }
    async _editComponent(componentId) {
        this.dialog.add(FormViewDialog, {
            resModel: "whatsapp.flow.component",
            resId:    componentId,
            title:    "Edit Component",
            onRecordSaved: async () => { await this._loadData(); },
        });
    }
    _confirmDeleteScreen(screenId) {
        const sc = this.state.screensById[screenId];
        if (!sc) return;
        this.dialog.add(ConfirmationDialog, {
            title: "Delete screen",
            body:  `Permanently delete screen "${sc.screen_id}" and its ${sc.components.length} component(s)?`,
            confirmLabel: "Delete",
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("whatsapp.flow.screen", [screenId]);
                this.state.selectedScreenId = null;
                await this._loadData();
                this.notif.add(`Deleted ${sc.screen_id}`, { type: "success" });
            },
            cancel: () => {},
        });
    }
    _confirmDeleteComponent(componentId, label) {
        this.dialog.add(ConfirmationDialog, {
            title: "Delete component",
            body:  `Delete this component${label ? ` (${label})` : ""}?`,
            confirmLabel: "Delete",
            confirmClass: "btn-danger",
            confirm: async () => {
                await this.orm.unlink("whatsapp.flow.component", [componentId]);
                await this._loadData();
            },
            cancel: () => {},
        });
    }
    async _renameScreenTitle(screenId, newTitle) {
        const sc = this.state.screensById[screenId];
        if (!sc || (sc.title || "") === newTitle) return;
        await this.orm.write("whatsapp.flow.screen", [screenId], { title: newTitle });
        sc.title = newTitle;
    }
    _selectScreen(screenId) {
        this.state.selectedScreenId = screenId;
        if (window.innerWidth < 900) this.state.panelVisible = true;
        // Selection is a visual-only change; swap the class in place so we
        // don't have to re-render the whole canvas.
        const grid = this.canvasRef.el?.querySelector(".o_flow_grid");
        if (!grid) return;
        for (const c of grid.querySelectorAll(".o_flow_card")) {
            c.classList.toggle(
                "o_flow_card_selected", +c.dataset.id === screenId,
            );
        }
    }

    // ── Canvas rendering ────────────────────────────────────────────────

    _buildTree() {
        // Build a DAG → tree by following navigate edges from entry. Each
        // screen appears once. Orphans are appended as roots. The first
        // navigate target of each screen becomes the "spine" child (placed
        // below the parent). All other navigate targets become "branches"
        // (placed to the right of the parent at the same y level).
        const visited = new Set();
        const make = (id) => {
            if (visited.has(id)) return null;
            visited.add(id);
            const sc = this.state.screensById[id];
            if (!sc) return null;
            const kidIds = sc.navTargets
                .map(t => t.id)
                .filter(tid => !visited.has(tid) && this.state.screensById[tid]);

            // Pick the spine: prefer the first target that does NOT loop
            // straight back to this node. That's the "hub" pattern used by
            // Meta's dispatcher screens (WORK_EXPERIENCE_SUMMARY etc.),
            // where four of five targets are "add another" variants that
            // navigate back to the hub and only one continues down the
            // main flow. Falls back to the first target if every option
            // loops back.
            let spineIx = 0;
            for (let i = 0; i < kidIds.length; i++) {
                const tsc = this.state.screensById[kidIds[i]];
                const loopsBack = tsc.navTargets.some(t => t.id === id);
                if (!loopsBack) { spineIx = i; break; }
            }
            const spineIds  = kidIds.length ? [kidIds[spineIx]] : [];
            const branchIds = kidIds.filter((_, i) => i !== spineIx);
            return {
                id, screen: sc,
                spine:    spineIds.map(make).filter(Boolean),
                branches: branchIds.map(make).filter(Boolean),
            };
        };
        const roots = [];
        const entry = this.state.entryScreenId;
        if (entry && this.state.screensById[entry]) {
            const node = make(entry);
            if (node) roots.push(node);
        }

        // Peer-alternative absorption: real Meta flows (e.g. Resume Helper's
        // repeated WORK_EXPERIENCE_TWO/THREE/FOUR/FIVE) use dynamic routing
        // — the "extra" screens are orphans that all share the same next
        // navigation target as a spine node. Attach each orphan as a right
        // branch of the node whose spine child matches its target, so peer
        // alternatives sit next to the primary instead of floating up as
        // top-row roots with long down-curving arrows.
        const collect = (n, out) => {
            out.set(n.id, n);
            for (const s of n.spine    || []) collect(s, out);
            for (const b of n.branches || []) collect(b, out);
        };
        const nodesById = new Map();
        for (const r of roots) collect(r, nodesById);

        for (const sc of this.state.screens) {
            if (visited.has(sc.id)) continue;
            if (sc.navTargets.length !== 1) continue;
            const targetId = sc.navTargets[0].id;
            let siblingNode = null;
            for (const [, node] of nodesById) {
                if ((node.spine || []).some(s => s.id === targetId)) {
                    siblingNode = node;
                    break;
                }
            }
            if (siblingNode) {
                const orphanNode = make(sc.id);
                if (orphanNode) {
                    siblingNode.branches.push(orphanNode);
                    collect(orphanNode, nodesById);
                }
            }
        }

        // Anything still unvisited becomes an extra top-row root.
        for (const sc of this.state.screens) {
            if (!visited.has(sc.id)) {
                const node = make(sc.id);
                if (node) roots.push(node);
            }
        }
        return roots;
    }

    // Assigns (col, level) to every node in the spine-plus-branches tree.
    // Spine children stay in the parent's column, one level deeper. Each
    // branch spawns its own column-cluster to the right of the parent at
    // the parent's level; the branch's own spine goes further down.
    // Returns { minCol, maxCol, maxLevel } for the visited subtree.
    _layoutSubtree(node, col, level) {
        node._col   = col;
        node._level = level;
        let maxCol = col, maxLevel = level;

        // Branches first — arrayed immediately to the right of the node so
        // peer alternatives stay tight to their parent instead of being
        // shoved past the entire spine subtree.
        let branchStartCol = col + 1;
        for (const b of node.branches || []) {
            const r = this._layoutSubtree(b, branchStartCol, level);
            branchStartCol = r.maxCol + 1;
            maxCol   = Math.max(maxCol,   r.maxCol);
            maxLevel = Math.max(maxLevel, r.maxLevel);
        }

        // Spine continues at the parent's column, one row deeper. Its own
        // subtree extends further right / deeper; we track those so
        // subsequent sibling branches don't collide.
        for (const s of node.spine || []) {
            const r = this._layoutSubtree(s, col, level + 1);
            maxCol   = Math.max(maxCol,   r.maxCol);
            maxLevel = Math.max(maxLevel, r.maxLevel);
        }

        return { minCol: col, maxCol, maxLevel };
    }

    _flattenLayout(node, parent, out) {
        out.push({
            id:     node.id,
            screen: node.screen,
            _col:   node._col,
            level:  node._level,
            parent,
        });
        for (const s of node.spine    || []) this._flattenLayout(s, node.id, out);
        for (const b of node.branches || []) this._flattenLayout(b, node.id, out);
        return out;
    }

    _renderCanvas() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        canvas.querySelectorAll(".o_flow_grid, .o_flow_empty").forEach(n => n.remove());
        canvas.removeEventListener("click", this._canvasClickFn);
        this._drawLinesFn = null;

        const tree = this._buildTree();
        if (!tree.length) {
            const empty = document.createElement("div");
            empty.className = "o_flow_empty";
            empty.innerHTML = `
                <div class="o_view_nocontent_smiling_face"></div>
                <p class="fw-bold">No screens yet</p>
                <p class="text-muted">Add screens from the flow form (or pick a template).</p>`;
            canvas.appendChild(empty);
            return;
        }

        // Spine + branch layout. Roots are laid out side-by-side (each in
        // its own column-cluster). Every node ends up with a _col + level.
        let rootStartCol = 0;
        const flat = [];
        for (const root of tree) {
            const r = this._layoutSubtree(root, rootStartCol, 0);
            this._flattenLayout(root, null, flat);
            rootStartCol = r.maxCol + 1;
        }

        const CARD_W = 280, GAP = 50, VGAP = 70, PX = 80, PY = 60;
        // Fallback row height in case a browser reports zero on measure
        // (extremely rare); real spacing is computed after mount below.
        const ROW_H_FALLBACK = 260;
        const totalCols = (flat.reduce((m, n) => Math.max(m, n._col), 0) + 1) || 1;
        const totalRows = flat.reduce((m, n) => Math.max(m, n.level), 0) + 1;

        const grid = document.createElement("div");
        grid.className = "o_flow_grid";
        grid.style.transform       = `scale(${this.state.zoom})`;
        grid.style.transformOrigin = "top center";
        grid.style.width  = Math.max(totalCols * (CARD_W + GAP) + PX * 2, 800) + "px";
        grid.style.height = (totalRows * (ROW_H_FALLBACK + VGAP) + PY * 2) + "px";

        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "o_flow_svg");
        grid.appendChild(svg);

        // Initial placement — vertical positions will be corrected after
        // cards mount and we can measure their real heights per row.
        for (const node of flat) {
            const card = this._buildCard(node.screen, node.id === this.state.entryScreenId);
            card.style.position = "absolute";
            card.style.left = Math.round(node._col * (CARD_W + GAP) + PX) + "px";
            card.style.top  = Math.round(node.level * (ROW_H_FALLBACK + VGAP) + PY) + "px";
            card.style.width = CARD_W + "px";
            card.dataset.id     = node.id;
            card.dataset.parent = node.parent || "";
            card.dataset.level  = String(node.level);
            grid.appendChild(card);
        }

        canvas.appendChild(grid);
        canvas.addEventListener("click", this._canvasClickFn);

        // Row-relayout: after cards paint, measure each row's tallest card
        // and reflow so nothing overlaps regardless of pill-wrap count.
        const relayoutRows = () => {
            const cards = [...grid.querySelectorAll(".o_flow_card")];
            const byLevel = new Map();
            for (const c of cards) {
                const lvl = +c.dataset.level;
                if (!byLevel.has(lvl)) byLevel.set(lvl, []);
                byLevel.get(lvl).push(c);
            }
            const levels = [...byLevel.keys()].sort((a, b) => a - b);
            let y = PY;
            for (const lvl of levels) {
                const row = byLevel.get(lvl);
                const maxH = Math.max(...row.map(c => c.offsetHeight || ROW_H_FALLBACK));
                for (const c of row) {
                    c.style.top = Math.round(y) + "px";
                }
                y += maxH + VGAP;
            }
            grid.style.height = Math.round(y + PY) + "px";
        };
        this._relayoutRowsFn = relayoutRows;

        const drawLines = () => {
            const w = grid.scrollWidth, h = grid.scrollHeight;
            svg.setAttribute("width", w); svg.setAttribute("height", h);
            svg.style.width = w + "px"; svg.style.height = h + "px";
            svg.innerHTML = "";

            const NS = "http://www.w3.org/2000/svg";
            const cards = [...grid.querySelectorAll(".o_flow_card")];
            const byScreenId = Object.fromEntries(cards.map(c => [c.dataset.id, c]));

            // Primary navigate edges (each screen → each navigate target).
            // Branches (target is roughly at the parent's y-level) get a
            // side-to-side S-curve; spine children keep the top-to-bottom
            // bezier.
            const OVERLAP_TOL = 40;   // px — considered "same row"
            for (const sc of this.state.screens) {
                const src = byScreenId[sc.id]; if (!src) continue;
                const srcTop  = src.offsetTop;
                const srcBot  = src.offsetTop + src.offsetHeight;
                for (const t of sc.navTargets) {
                    const tgt = byScreenId[t.id]; if (!tgt) continue;
                    const tgtTop = tgt.offsetTop;
                    const tgtBot = tgt.offsetTop + tgt.offsetHeight;

                    const isSideBranch = (
                        tgt.offsetLeft > src.offsetLeft + src.offsetWidth - 10
                        && tgtBot > srcTop - OVERLAP_TOL
                        && tgtTop < srcBot + OVERLAP_TOL
                    );

                    let x1, y1, x2, y2, cp1x, cp1y, cp2x, cp2y;
                    if (isSideBranch) {
                        // Right side of source → left side of target.
                        x1 = src.offsetLeft + src.offsetWidth;
                        y1 = src.offsetTop + src.offsetHeight / 2;
                        x2 = tgt.offsetLeft;
                        y2 = tgt.offsetTop + tgt.offsetHeight / 2;
                        const mx = (x1 + x2) / 2;
                        cp1x = mx; cp1y = y1;
                        cp2x = mx; cp2y = y2;
                    } else {
                        // Bottom of source → top of target (spine).
                        x1 = src.offsetLeft + src.offsetWidth / 2;
                        y1 = srcBot;
                        x2 = tgt.offsetLeft + tgt.offsetWidth / 2;
                        y2 = tgtTop;
                        const my = (y1 + y2) / 2;
                        cp1x = x1; cp1y = my;
                        cp2x = x2; cp2y = my;
                    }

                    const path = document.createElementNS(NS, "path");
                    path.setAttribute(
                        "d",
                        `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`
                    );
                    path.setAttribute("class", "o_flow_connector");
                    svg.appendChild(path);

                    const dot = document.createElementNS(NS, "circle");
                    dot.setAttribute("cx", x2); dot.setAttribute("cy", y2);
                    dot.setAttribute("r", "4"); dot.setAttribute("fill", "#818cf8");
                    svg.appendChild(dot);

                    const lx = (x1 + x2) / 2, ly = (y1 + y2) / 2;
                    let txt = (t.label || "navigate").slice(0, 24);
                    const aw = Math.min(txt.length * 6.4 + 18, 220);
                    const bg = document.createElementNS(NS, "rect");
                    bg.setAttribute("x", lx - aw/2); bg.setAttribute("y", ly - 10);
                    bg.setAttribute("width", aw); bg.setAttribute("height", 20);
                    bg.setAttribute("rx", "10"); bg.setAttribute("class", "o_flow_lbl_bg");
                    svg.appendChild(bg);
                    const lbl = document.createElementNS(NS, "text");
                    lbl.setAttribute("x", lx); lbl.setAttribute("y", ly + 1);
                    lbl.setAttribute("text-anchor", "middle");
                    lbl.setAttribute("dominant-baseline", "middle");
                    lbl.setAttribute("class", "o_flow_lbl_txt");
                    lbl.textContent = txt;
                    svg.appendChild(lbl);
                }
            }
        };

        this._drawLinesFn = drawLines;
        // Layout + wire pass: reflow rows first (needs card heights), then
        // draw connectors that depend on the settled Y coordinates.
        setTimeout(() => {
            relayoutRows();
            drawLines();
            setTimeout(() => { relayoutRows(); drawLines(); }, 150);
        }, 60);
    }

    _buildCard(sc, isEntry) {
        const card = document.createElement("div");
        card.className = "o_flow_card";
        if (sc.id === this.state.selectedScreenId) {
            card.classList.add("o_flow_card_selected");
        }
        const cfg = sc.success ? SCREEN_CFG_SUCCESS
                  : sc.terminal ? SCREEN_CFG_TERMINAL
                  : isEntry ? SCREEN_CFG_ENTRY
                  : SCREEN_CFG_DEFAULT;
        card.style.background  = cfg.bg;
        card.style.borderColor = cfg.border;

        const badgeText = sc.success ? "success"
                       : sc.terminal ? "terminal"
                       : isEntry ? "entry"
                       : "";

        // Head: id + title + badge
        const head = document.createElement("div");
        head.className = "o_flow_card_head";
        head.innerHTML = `
            <span class="o_flow_card_type_icon">🪟</span>
            <span class="o_flow_card_name" title="${esc(sc.title)}">${esc(sc.screen_id)}</span>
            ${badgeText ? `<span class="o_flow_card_badge" style="background:${cfg.color};">${badgeText}</span>` : ""}
        `;
        card.appendChild(head);

        // Subtitle: title (inline-editable like the chatbot card name).
        const sub = document.createElement("div");
        sub.className = "o_flow_card_subtitle";
        sub.setAttribute("contenteditable", "true");
        sub.setAttribute("spellcheck", "false");
        sub.textContent = sc.title || "(click to add a title)";
        if (!sc.title) sub.classList.add("o_flow_card_subtitle_placeholder");
        sub.addEventListener("click", (ev) => ev.stopPropagation());
        sub.addEventListener("focus", () => {
            if (!sc.title) sub.textContent = "";
            sub.classList.remove("o_flow_card_subtitle_placeholder");
        });
        sub.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") { ev.preventDefault(); sub.blur(); }
            if (ev.key === "Escape") {
                sub.textContent = sc.title || "(click to add a title)";
                if (!sc.title) sub.classList.add("o_flow_card_subtitle_placeholder");
                sub.blur();
            }
        });
        sub.addEventListener("blur", async () => {
            const next = sub.textContent.trim();
            await this._renameScreenTitle(sc.id, next);
            if (!next) {
                sub.textContent = "(click to add a title)";
                sub.classList.add("o_flow_card_subtitle_placeholder");
            }
        });
        card.appendChild(sub);

        // Content: top 5 component types as pills
        const content = document.createElement("div");
        content.className = "o_flow_card_content";
        const pills = sc.components.slice(0, 6).map(c => {
            const cc = TYPE_CFG[c.component_type] || { icon: "•", color: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" };
            const lbl = esc((c.label || c.text || c.name || "").slice(0, 18));
            return `<span class="o_flow_pill" style="background:${cc.bg};border-color:${cc.border};color:${cc.color};" title="${esc(c.component_type)}: ${esc(c.label || c.text || c.name || "")}">${cc.icon} ${lbl}</span>`;
        }).join("");
        const remaining = sc.components.length - 6;
        const more = remaining > 0
            ? `<span class="o_flow_pill o_flow_pill_more">+${remaining} more</span>`
            : "";
        content.innerHTML = sc.components.length
            ? `<div class="o_flow_pills">${pills}${more}</div>`
            : `<div class="o_flow_card_empty">No components yet</div>`;
        card.appendChild(content);

        // Foot: component count + complete/url badges
        const foot = document.createElement("div");
        foot.className = "o_flow_card_foot";
        const compCount = sc.components.length;
        foot.innerHTML = `
            <span class="o_flow_card_stat"><strong>${compCount}</strong> component${compCount === 1 ? "" : "s"}</span>
            ${sc.completes.length ? `<span class="o_flow_card_end" title="Completes the flow">✓ ends flow</span>` : ""}
            ${sc.openUrls.length ? `<span class="o_flow_card_url" title="Opens an external URL">↗ external link</span>` : ""}
        `;
        card.appendChild(foot);

        // Hover-revealed Add Component pill at the bottom of the card.
        const addBtn = document.createElement("button");
        addBtn.className = "o_flow_card_add_comp";
        addBtn.title = "Add component to this screen";
        addBtn.innerHTML = '<i class="fa fa-plus"/> Component';
        addBtn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            this._addComponent(sc.id);
        });
        card.appendChild(addBtn);

        card.addEventListener("click", (ev) => {
            ev.stopPropagation();
            this._selectScreen(sc.id);
        });
        return card;
    }

    // ── Right panel: properties helpers ─────────────────────────────────

    componentIcon(t) {
        return (TYPE_CFG[t] && TYPE_CFG[t].icon) || "•";
    }
    componentLabel(t) {
        return (TYPE_CFG[t] && TYPE_CFG[t].label) || t;
    }
    componentColor(t) {
        return (TYPE_CFG[t] && TYPE_CFG[t].color) || "#6b7280";
    }
    componentBg(t) {
        return (TYPE_CFG[t] && TYPE_CFG[t].bg) || "#f9fafb";
    }
    actionHint(c) {
        if (c.action_type === "navigate" && Array.isArray(c.target_screen_id)) {
            return { kind: "nav", text: c.target_screen_id[1] || "screen" };
        }
        if (c.action_type === "complete") return { kind: "end", text: "completes flow" };
        if (c.action_type === "open_url")  return { kind: "url", text: c.open_url || "" };
        return null;
    }
    targetScreenName(c) {
        return Array.isArray(c.target_screen_id) ? c.target_screen_id[1] : "";
    }
    // Template helper: OWL's t-esc scope doesn't expose the global JSON
    // object, so we wrap the stringify call in a component method.
    formatPreviewValue(v) {
        if (v === undefined) return "";
        try { return JSON.stringify(v); }
        catch (e) { return String(v); }
    }
    previewValueKeys() {
        return Object.keys(this.state.preview.values || {});
    }
    // Split components into body / footer so the Footer button can be
    // anchored at the bottom of the phone chrome while the body scrolls.
    previewBodyComponents() {
        const sc = this.previewScreen;
        if (!sc) return [];
        return sc.components.filter(c => c.component_type !== "Footer");
    }
    previewFooter() {
        const sc = this.previewScreen;
        if (!sc) return null;
        return sc.components.find(c => c.component_type === "Footer") || null;
    }
}

registry.category("actions").add("comm_whatsapp.flow_canvas", FlowCanvasAction);
