/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// ── Step type display config ──────────────────────────────────────────────────
const TYPE_CFG = {
    message:              { icon: "💬", label: "Message",       color: "#1a73e8", bg: "#e8f0fe", border: "#93c5fd" },
    question_text:        { icon: "✏️",  label: "Question",      color: "#7c3aed", bg: "#f5f3ff", border: "#c4b5fd" },
    question_numeric:     { icon: "🔢", label: "Number",        color: "#ea580c", bg: "#fff7ed", border: "#fdb57a" },
    question_phone:       { icon: "📱", label: "Phone",         color: "#0891b2", bg: "#ecfeff", border: "#67e8f9" },
    question_email:       { icon: "📧", label: "Email",         color: "#4f46e5", bg: "#eef2ff", border: "#a5b4fc" },
    question_date:        { icon: "📅", label: "Date",          color: "#be185d", bg: "#fdf2f8", border: "#f9a8d4" },
    question_document:    { icon: "📄", label: "Document",      color: "#475569", bg: "#f8fafc", border: "#cbd5e1" },
    question_image:       { icon: "🖼️", label: "Image",         color: "#b45309", bg: "#fffbeb", border: "#fcd34d" },
    question_video:       { icon: "🎬", label: "Video",         color: "#dc2626", bg: "#fef2f2", border: "#fca5a5" },
    question_audio:       { icon: "🎵", label: "Audio",         color: "#db2777", bg: "#fdf2f8", border: "#f9a8d4" },
    question_interactive: { icon: "🔘", label: "Interactive",   color: "#0284c7", bg: "#f0f9ff", border: "#7dd3fc" },
    set_variable:         { icon: "📝", label: "Set Variable",  color: "#d97706", bg: "#fffbeb", border: "#fcd34d" },
    execute_code:         { icon: "⚡", label: "Execute Code",  color: "#374151", bg: "#f3f4f6", border: "#9ca3af" },
    end_flow:             { icon: "✅", label: "End Flow",      color: "#16a34a", bg: "#f0fdf4", border: "#86efac" },
};
const DEFAULT_CFG = { icon: "●", label: "Step", color: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" };

// ── Reingold-Tilford column layout ────────────────────────────────────────────
let _colCtr = 0;
function assignCols(nodes) {
    for (const n of nodes) {
        const kids = n.children || [];
        if (!kids.length) { n._col = _colCtr++; }
        else {
            const start = _colCtr;
            assignCols(kids);
            n._col = (start + _colCtr - 1) / 2;
        }
    }
}
function flattenTree(nodes, level = 0, parent = null, out = []) {
    for (const n of nodes) {
        out.push({ id: n.id, name: n.name, type: n.type, level, parent,
                   _col: n._col, preview_html: n.preview_html,
                   answers: n.answers, children: n.children });
        flattenTree(n.children || [], level + 1, n.id, out);
    }
    return out;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function bodyToHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>")
        .replace(/_([^_\n]+)_/g, "<em>$1</em>")
        .replace(/\n/g, "<br>");
}

// ── Client action component ───────────────────────────────────────────────────
export class ChatbotFlowAction extends Component {
    static template = "comm_whatsapp_chatbot.ChatbotFlowAction";
    static props = ["action", "actionId?"];

    setup() {
        this.orm    = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.chatbotId   = this.props.action.params?.chatbot_id;
        this.canvasRef   = useRef("canvas");
        this._tree       = [];
        this._drawLinesFn = null;
        this._pendingDraw = false;
        this._onResize    = () => { if (this._drawLinesFn) this._drawLinesFn(); };

        this.state = useState({
            loading:     true,
            chatbotName: this.props.action.params?.chatbot_name || "",
            zoom:        1,
        });

        onMounted(()  => this._loadData());
        onPatched(()  => {
            if (this._pendingDraw && this.canvasRef.el) {
                this._pendingDraw = false;
                this._renderCanvas();
            }
        });
        onWillUnmount(() => window.removeEventListener("resize", this._onResize));
    }

    // ── Data ─────────────────────────────────────────────────────────────────

    async _loadData() {
        this._pendingDraw = false;
        this.state.loading = true;

        const steps = await this.orm.searchRead(
            "whatsapp.chatbot.step",
            [["chatbot_id", "=", this.chatbotId]],
            ["id", "name", "step_type", "parent_id", "body_plain", "sequence", "trigger_answer_ids"],
            { order: "parent_path, sequence, id" }
        );

        // Resolve answer names
        const allIds = [...new Set(steps.flatMap(s => s.trigger_answer_ids || []))];
        const ansById = {};
        if (allIds.length) {
            const ans = await this.orm.read("whatsapp.chatbot.answer", allIds, ["id", "value"]);
            ans.forEach(a => { ansById[a.id] = a.value; });
        }

        this._tree = this._buildTree(steps, ansById);
        this.state.loading = false;
        this._pendingDraw  = true;
        // onPatched fires after OWL removes the loading spinner → _renderCanvas runs
    }

    _buildTree(steps, ansById) {
        const byParent = {};
        for (const s of steps) {
            const pid = Array.isArray(s.parent_id) ? s.parent_id[0] : 0;
            (byParent[pid] = byParent[pid] || []).push(s);
        }
        for (const list of Object.values(byParent)) {
            list.sort((a, b) => a.sequence - b.sequence);
        }
        const noPreview = new Set(["execute_code", "set_variable", "end_flow"]);
        const build = pid => (byParent[pid] || []).map(s => ({
            id:           s.id,
            name:         s.name,
            type:         s.step_type,
            preview_html: noPreview.has(s.step_type) ? "" : bodyToHtml(s.body_plain),
            answers:      (s.trigger_answer_ids || []).map(id => ansById[id] || `#${id}`),
            children:     build(s.id),
        }));
        return build(0);
    }

    // ── Native Odoo dialogs ───────────────────────────────────────────────────

    _openEditDialog(stepId) {
        this.dialog.add(FormViewDialog, {
            resModel:      "whatsapp.chatbot.step",
            resId:         stepId,
            title:         "Edit Step",
            onRecordSaved: () => this._loadData(),
        });
    }

    _openCreateDialog(parentId) {
        this.dialog.add(FormViewDialog, {
            resModel: "whatsapp.chatbot.step",
            context:  {
                default_chatbot_id: this.chatbotId,
                ...(parentId ? { default_parent_id: parentId } : {}),
            },
            title:         parentId ? "New Step" : "New Root Step",
            onRecordSaved: () => this._loadData(),
        });
    }

    _confirmDelete(stepId, hasChildren) {
        this.dialog.add(ConfirmationDialog, {
            body: hasChildren
                ? "Delete this step and all its children? This cannot be undone."
                : "Delete this step? This cannot be undone.",
            confirmLabel: "Delete",
            confirm: async () => {
                try {
                    await this.orm.unlink("whatsapp.chatbot.step", [stepId]);
                    await this._loadData();
                } catch (e) {
                    this.notification.add(e.data?.message || "Could not delete step.", { type: "danger" });
                }
            },
            cancel: () => {},
        });
    }

    async _saveStepName(stepId, name) {
        await this.orm.write("whatsapp.chatbot.step", [stepId], { name });
    }

    // ── Zoom ─────────────────────────────────────────────────────────────────

    _setZoom(z) {
        this.state.zoom = Math.min(2, Math.max(0.4, Math.round(z * 10) / 10));
        const grid = this.canvasRef.el?.querySelector(".o_flow_grid");
        if (grid) { grid.style.transform = `scale(${this.state.zoom})`; grid.style.transformOrigin = "top center"; }
        if (this._drawLinesFn) this._drawLinesFn();
    }

    get zoomLabel() { return Math.round(this.state.zoom * 100) + "%"; }

    // ── Canvas ────────────────────────────────────────────────────────────────

    _renderCanvas() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        canvas.querySelectorAll(".o_flow_grid, .o_flow_empty").forEach(n => n.remove());
        window.removeEventListener("resize", this._onResize);
        this._drawLinesFn = null;

        if (!this._tree.length) {
            const empty = document.createElement("div");
            empty.className = "o_flow_empty";
            empty.innerHTML = `
                <div class="o_view_nocontent_smiling_face"></div>
                <p class="fw-bold">No steps yet</p>
                <p class="text-muted">Click <strong>Add Step</strong> in the toolbar to start building your flow.</p>`;
            canvas.appendChild(empty);
            return;
        }

        // Column layout
        _colCtr = 0;
        assignCols(this._tree);
        const flat = flattenTree(this._tree);

        const CARD_W = 260, GAP = 40, ROW_H = 230, PX = 80, PY = 60;
        const totalCols = _colCtr || 1;
        const totalRows = flat.reduce((m, n) => Math.max(m, n.level), 0) + 1;

        const grid = document.createElement("div");
        grid.className = "o_flow_grid";
        grid.style.transform       = `scale(${this.state.zoom})`;
        grid.style.transformOrigin = "top center";
        grid.style.width  = Math.max(totalCols * (CARD_W + GAP) + PX * 2, 800) + "px";
        grid.style.height = (totalRows * ROW_H + PY * 2 + 80) + "px";

        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.className = "o_flow_svg";
        grid.appendChild(svg);

        const nodeById = Object.fromEntries(flat.map(n => [n.id, n]));

        for (const node of flat) {
            const card = this._buildCard(node);
            card.style.position = "absolute";
            card.style.left  = Math.round(node._col * (CARD_W + GAP) + PX) + "px";
            card.style.top   = Math.round(node.level * ROW_H + PY) + "px";
            card.style.width = CARD_W + "px";
            grid.appendChild(card);
        }

        canvas.appendChild(grid);

        const drawLines = () => {
            const w = grid.scrollWidth, h = grid.scrollHeight;
            svg.setAttribute("width", w); svg.setAttribute("height", h);
            svg.style.width = w + "px"; svg.style.height = h + "px";
            svg.innerHTML = "";

            const NS = "http://www.w3.org/2000/svg";
            const defs   = document.createElementNS(NS, "defs");
            const marker = document.createElementNS(NS, "marker");
            marker.setAttribute("id", "o-flow-arr");
            marker.setAttribute("markerWidth", "7"); marker.setAttribute("markerHeight", "7");
            marker.setAttribute("refX", "0"); marker.setAttribute("refY", "3.5");
            marker.setAttribute("orient", "auto"); marker.setAttribute("markerUnits", "strokeWidth");
            const mp = document.createElementNS(NS, "path");
            mp.setAttribute("d", "M0,0 L0,7 L5,3.5 z"); mp.setAttribute("fill", "#adb5bd");
            marker.appendChild(mp); defs.appendChild(marker); svg.appendChild(defs);

            const gr = grid.getBoundingClientRect();
            const byId = Object.fromEntries([...grid.querySelectorAll(".o_flow_card")].map(c => [c.dataset.id, c]));

            for (const child of grid.querySelectorAll(".o_flow_card")) {
                const pid = child.dataset.parent; if (!pid) continue;
                const par = byId[pid]; if (!par) continue;
                const pr = par.getBoundingClientRect(), cr = child.getBoundingClientRect();
                const x1 = pr.left + pr.width  / 2 - gr.left;
                const y1 = pr.bottom - gr.top + 14; // 14 = add-btn protrusion
                const x2 = cr.left + cr.width  / 2 - gr.left;
                const y2 = cr.top  - gr.top;
                if ([x1,y1,x2,y2].some(isNaN)) continue;
                const my = (y1 + y2) / 2;
                const path = document.createElementNS(NS, "path");
                path.setAttribute("d", `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`);
                path.setAttribute("class", "o_flow_connector");
                path.setAttribute("marker-end", "url(#o-flow-arr)");
                svg.appendChild(path);

                // Connector label for trigger answers
                const nd = nodeById[parseInt(child.dataset.id)];
                if (nd?.answers?.length) {
                    const lx = (x1 + x2) / 2, ly = (y1 + y2) / 2;
                    let txt = nd.answers.join(" / ");
                    if (txt.length > 26) txt = txt.slice(0, 23) + "…";
                    const aw = Math.min(txt.length * 6.4 + 18, 190);
                    const bg = document.createElementNS(NS, "rect");
                    bg.setAttribute("x", lx - aw/2); bg.setAttribute("y", ly - 10);
                    bg.setAttribute("width", aw); bg.setAttribute("height", 20);
                    bg.setAttribute("rx", "10"); bg.setAttribute("class", "o_flow_lbl_bg");
                    svg.appendChild(bg);
                    const lbl = document.createElementNS(NS, "text");
                    lbl.setAttribute("x", lx); lbl.setAttribute("y", ly + 1);
                    lbl.setAttribute("text-anchor", "middle"); lbl.setAttribute("dominant-baseline", "middle");
                    lbl.setAttribute("class", "o_flow_lbl_txt"); lbl.textContent = txt;
                    svg.appendChild(lbl);
                }
            }
        };

        this._drawLinesFn = drawLines;
        setTimeout(() => { drawLines(); setTimeout(drawLines, 150); }, 60);
        window.addEventListener("resize", this._onResize, { passive: true });
        this._enableDragScroll(canvas);
    }

    _buildCard(node) {
        const cfg  = TYPE_CFG[node.type] || DEFAULT_CFG;
        const card = document.createElement("div");
        card.className  = "o_flow_card";
        card.dataset.id = node.id;
        if (node.parent) card.dataset.parent = node.parent;

        // Colored strip (like hierarchy view employee header)
        const strip = document.createElement("div");
        strip.className = "o_flow_card_strip";
        strip.style.background = cfg.color;

        const stripIcon = document.createElement("span");
        stripIcon.className   = "o_flow_card_icon";
        stripIcon.textContent = cfg.icon;
        strip.appendChild(stripIcon);
        card.appendChild(strip);

        // Card body
        const body = document.createElement("div");
        body.className = "o_flow_card_body";

        // Editable name
        const nameEl = document.createElement("div");
        nameEl.className       = "o_flow_card_name";
        nameEl.textContent     = node.name || `Step #${node.id}`;
        nameEl.contentEditable = "true";
        nameEl.title           = "Click to rename";
        let origName = nameEl.textContent;
        nameEl.addEventListener("focus",   ()  => { origName = nameEl.textContent; });
        nameEl.addEventListener("keydown", e   => {
            if (e.key === "Enter")  { e.preventDefault(); nameEl.blur(); }
            if (e.key === "Escape") { nameEl.textContent = origName; nameEl.blur(); }
        });
        nameEl.addEventListener("paste", e => {
            e.preventDefault();
            document.execCommand("insertText", false,
                (e.clipboardData || window.clipboardData).getData("text/plain"));
        });
        nameEl.addEventListener("blur", async () => {
            const n = nameEl.textContent.trim();
            if (!n || n === origName) { nameEl.textContent = origName; return; }
            if (!/^[A-Za-z\s-]+$/.test(n)) { nameEl.textContent = origName; return; }
            try { await this._saveStepName(node.id, n); origName = n; }
            catch { nameEl.textContent = origName; }
        });
        nameEl.addEventListener("mousedown", e => e.stopPropagation());
        body.appendChild(nameEl);

        // Type badge
        const badge = document.createElement("span");
        badge.className = "o_flow_card_badge";
        badge.style.background = cfg.color;
        badge.textContent = cfg.label;
        body.appendChild(badge);

        // Message preview bubble
        if (node.preview_html) {
            const bubble = document.createElement("div");
            bubble.className = "o_flow_bubble";
            bubble.innerHTML = node.preview_html;
            bubble.querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
            body.appendChild(bubble);
        }

        // Trigger answer chips
        if (node.answers?.length) {
            const chips = document.createElement("div");
            chips.className = "o_flow_chips";
            for (const a of node.answers) {
                const ch = document.createElement("span");
                ch.className = "o_flow_chip"; ch.textContent = a;
                chips.appendChild(ch);
            }
            body.appendChild(chips);
        }

        card.appendChild(body);

        // Footer action buttons
        const footer = document.createElement("div");
        footer.className = "o_flow_card_footer";

        const editBtn = document.createElement("button");
        editBtn.type = "button"; editBtn.className = "btn btn-sm o_flow_btn_edit";
        editBtn.innerHTML = '<i class="fa fa-pencil me-1"/>Edit';
        editBtn.addEventListener("click", e => { e.stopPropagation(); this._openEditDialog(node.id); });
        footer.appendChild(editBtn);

        const delBtn = document.createElement("button");
        delBtn.type = "button"; delBtn.className = "btn btn-sm o_flow_btn_del";
        delBtn.innerHTML = '<i class="fa fa-trash me-1"/>Delete';
        delBtn.addEventListener("click", e => {
            e.stopPropagation();
            this._confirmDelete(node.id, !!(node.children && node.children.length));
        });
        footer.appendChild(delBtn);
        card.appendChild(footer);

        // Add-child button
        const addBtn = document.createElement("button");
        addBtn.type = "button"; addBtn.className = "o_flow_add_btn"; addBtn.title = "Add next step";
        addBtn.innerHTML = '<i class="fa fa-plus"/>';
        addBtn.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); this._openCreateDialog(node.id); });
        card.appendChild(addBtn);

        return card;
    }

    _enableDragScroll(el) {
        let drag = false, sx = 0, sy = 0, ssl = 0, sst = 0;
        el.addEventListener("mousedown", e => {
            if (e.button !== 0) return;
            if (e.target.closest("[contenteditable]") || e.target.closest("button") || e.target.closest("a")) return;
            drag = true; el.classList.add("o_flow_dragging");
            sx = e.clientX; sy = e.clientY; ssl = el.scrollLeft; sst = el.scrollTop;
            e.preventDefault();
        });
        window.addEventListener("mousemove", e => {
            if (!drag) return;
            el.scrollLeft = ssl - (e.clientX - sx); el.scrollTop = sst - (e.clientY - sy);
        }, { passive: true });
        window.addEventListener("mouseup", () => { drag = false; el.classList.remove("o_flow_dragging"); });
        el.addEventListener("wheel", e => {
            if (!e.ctrlKey) return;
            e.preventDefault();
            this._setZoom(this.state.zoom + (e.deltaY < 0 ? 0.1 : -0.1));
        }, { passive: false });
    }
}

registry.category("actions").add("comm_whatsapp_chatbot.chatbot_flow", ChatbotFlowAction);
