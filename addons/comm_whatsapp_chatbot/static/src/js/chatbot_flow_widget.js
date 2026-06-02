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

const OP_PREFIX = {
    is_equal_to:      "= ",
    is_not_equal_to:  "≠ ",
    contains:         "~ ",
    does_not_contain: "!~ ",
    less_than:        "< ",
    greater_than:     "> ",
};

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
                   answers: n.answers, children: n.children,
                   waType: n.waType, buttons: n.buttons,
                   listBtnText: n.listBtnText, listRows: n.listRows,
                   headerType: n.headerType, headerText: n.headerText, footer: n.footer,
                   flowCta: n.flowCta, flowName: n.flowName,
                   sequence: n.sequence, answerDataType: n.answerDataType,
                   variableName: n.variableName, variableDataSource: n.variableDataSource,
                   variableValue: n.variableValue, sourceStepName: n.sourceStepName,
                   sourceVarName: n.sourceVarName });
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
        this.action = useService("action");
        this.notification = useService("notification");

        this.chatbotId   = this.props.action.params?.chatbot_id;
        this.canvasRef   = useRef("canvas");
        this._tree         = [];
        this._flat         = [];
        this._drawLinesFn  = null;
        this._pendingDraw  = false;
        this._onResize     = () => { if (this._drawLinesFn) this._drawLinesFn(); };
        this._canvasClickFn = () => {
            this.canvasRef.el?.querySelector(".o_flow_card_selected")
                ?.classList.remove("o_flow_card_selected");
            this.state.selectedNode = null;
        };

        this.state = useState({
            loading:      true,
            chatbotName:  this.props.action.params?.chatbot_name || "",
            zoom:         1,
            selectedNode: null,
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
        this.state.selectedNode = null;

        const steps = await this.orm.searchRead(
            "whatsapp.chatbot.step",
            [["chatbot_id", "=", this.chatbotId]],
            ["id", "name", "step_type", "parent_id", "body_plain", "sequence",
             "trigger_answer_ids", "trigger_variable_ids", "wa_message_type",
             "button_ids", "list_row_ids", "list_button_text",
             "header_type", "header_text", "footer", "flow_cta", "flow_id",
             "answer_data_type", "variable_id", "variable_data_source",
             "variable_value", "source_step_id", "source_variable_id"],
            { order: "parent_path, sequence, id" }
        );

        // Resolve answer names
        const allAnsIds = [...new Set(steps.flatMap(s => s.trigger_answer_ids || []))];
        const ansById = {};
        if (allAnsIds.length) {
            const ans = await this.orm.read("whatsapp.chatbot.answer", allAnsIds, ["id", "value", "operator"]);
            ans.forEach(a => { ansById[a.id] = { value: a.value, operator: a.operator }; });
        }

        // Resolve variable trigger labels
        const allVarTrigIds = [...new Set(steps.flatMap(s => s.trigger_variable_ids || []))];
        const varTrigById = {};
        if (allVarTrigIds.length) {
            const vts = await this.orm.read(
                "whatsapp.chatbot.variable.trigger", allVarTrigIds,
                ["id", "variable_id", "operator", "value"]
            );
            vts.forEach(vt => {
                const varName = Array.isArray(vt.variable_id) ? vt.variable_id[1] : "?";
                varTrigById[vt.id] = varName + " " + (OP_PREFIX[vt.operator] || "") + (vt.value || "");
            });
        }

        // Resolve reply button titles
        const allBtnIds = [...new Set(steps.flatMap(s => s.button_ids || []))];
        const btnById = {};
        if (allBtnIds.length) {
            const btns = await this.orm.read("whatsapp.chatbot.step.button", allBtnIds, ["id", "title"]);
            btns.forEach(b => { btnById[b.id] = b.title; });
        }

        // Resolve list row titles
        const allRowIds = [...new Set(steps.flatMap(s => s.list_row_ids || []))];
        const rowById = {};
        if (allRowIds.length) {
            const rows = await this.orm.read("whatsapp.chatbot.step.list.row", allRowIds, ["id", "title"]);
            rows.forEach(r => { rowById[r.id] = r.title; });
        }

        this._tree = this._buildTree(steps, ansById, varTrigById, btnById, rowById);
        this.state.loading = false;
        this._pendingDraw  = true;
        // onPatched fires after OWL removes the loading spinner → _renderCanvas runs
    }

    _buildTree(steps, ansById, varTrigById, btnById, rowById) {
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
            waType:       s.wa_message_type || "non_interactive",
            preview_html: noPreview.has(s.step_type) ? "" : bodyToHtml(s.body_plain),
            answers: [
                ...(s.trigger_answer_ids || []).map(id => {
                    const a = ansById[id];
                    if (!a) return `#${id}`;
                    return "User input " + (OP_PREFIX[a.operator] || "") + a.value;
                }),
                ...(s.trigger_variable_ids || []).map(id => varTrigById[id] || `#${id}`),
            ],
            buttons:      (s.button_ids   || []).map(id => btnById[id]).filter(Boolean),
            listBtnText:  s.list_button_text || "See all options",
            listRows:     (s.list_row_ids  || []).map(id => rowById[id]).filter(Boolean),
            headerType:         noPreview.has(s.step_type) ? null : (s.header_type || null),
            headerText:         s.header_text || "",
            footer:             noPreview.has(s.step_type) ? "" : (s.footer || ""),
            flowCta:            s.flow_cta || "",
            flowName:           Array.isArray(s.flow_id) ? s.flow_id[1] : "",
            sequence:           s.sequence,
            answerDataType:     s.answer_data_type || "",
            variableName:       Array.isArray(s.variable_id)       ? s.variable_id[1]       : "",
            variableDataSource: s.variable_data_source || "",
            variableValue:      s.variable_value || "",
            sourceStepName:     Array.isArray(s.source_step_id)    ? s.source_step_id[1]    : "",
            sourceVarName:      Array.isArray(s.source_variable_id)? s.source_variable_id[1]: "",
            children:           build(s.id),
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

    _goBack() {
        history.back();
    }

    // ── Type config (also called from OWL template) ───────────────────────────

    typeCfg(type) { return TYPE_CFG[type] || DEFAULT_CFG; }

    waTypeLabel(t) {
        return { non_interactive: "Plain", interactive_button: "Reply Buttons",
                 interactive_list: "List", interactive_flow: "Flow" }[t] || t;
    }
    waTypeBadgeColor(t) {
        return { non_interactive: "#9ca3af", interactive_button: "#3b82f6",
                 interactive_list: "#6366f1", interactive_flow: "#16a34a" }[t] || "#9ca3af";
    }
    answerTypeLabel(t) {
        return { text: "Text", integer: "Integer", float: "Decimal", date: "Date",
                 boolean: "Boolean", document: "Document", image: "Image",
                 video: "Video", audio: "Audio" }[t] || t;
    }
    headerTypeLabel(t) {
        return { text: "Text", document: "Document", image: "Image", video: "Video" }[t] || t;
    }
    headerTypeIcon(t) {
        return { text: "fa-font", document: "fa-file-text-o",
                 image: "fa-image", video: "fa-play-circle" }[t] || "fa-question";
    }
    varSourceLabel(s, node) {
        if (s === "static")   return `Static: "${node.variableValue || "—"}"`;
        if (s === "answer")   return `From answer: ${node.sourceStepName || "—"}`;
        if (s === "variable") return `From variable: ${node.sourceVarName || "—"}`;
        return s;
    }
    isQuestionType(t) { return t && t.startsWith("question_"); }

    // ── Position persistence (localStorage) ──────────────────────────────────

    _loadPositions() {
        try { return JSON.parse(localStorage.getItem(`chatbot_flow_pos_${this.chatbotId}`) || "{}"); }
        catch { return {}; }
    }

    _savePositions(pos) {
        try { localStorage.setItem(`chatbot_flow_pos_${this.chatbotId}`, JSON.stringify(pos)); }
        catch {}
    }

    _resetLayout() {
        try { localStorage.removeItem(`chatbot_flow_pos_${this.chatbotId}`); } catch {}
        this._loadData();
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
        canvas.removeEventListener("click", this._canvasClickFn);
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
        svg.setAttribute("class", "o_flow_svg");
        grid.appendChild(svg);

        const nodeById  = Object.fromEntries(flat.map(n => [n.id, n]));
        const savedPos  = this._loadPositions();
        this._flat      = flat;

        for (const node of flat) {
            const card = this._buildCard(node);
            card.style.position = "absolute";
            const sp = savedPos[node.id];
            card.style.left  = (sp ? sp.x : Math.round(node._col * (CARD_W + GAP) + PX)) + "px";
            card.style.top   = (sp ? sp.y : Math.round(node.level * ROW_H + PY)) + "px";
            card.style.width = CARD_W + "px";
            grid.appendChild(card);
            this._makeCardDraggable(card, node.id);
        }

        canvas.appendChild(grid);
        canvas.addEventListener("click", this._canvasClickFn);

        const drawLines = () => {
            const w = grid.scrollWidth, h = grid.scrollHeight;
            svg.setAttribute("width", w); svg.setAttribute("height", h);
            svg.style.width = w + "px"; svg.style.height = h + "px";
            svg.innerHTML = "";

            const NS = "http://www.w3.org/2000/svg";

            // offsetLeft/offsetTop: logical coords relative to grid — zoom-independent
            const byId = Object.fromEntries([...grid.querySelectorAll(".o_flow_card")].map(c => [c.dataset.id, c]));

            for (const child of grid.querySelectorAll(".o_flow_card")) {
                const pid = child.dataset.parent; if (!pid) continue;
                const par = byId[pid]; if (!par) continue;
                const x1 = par.offsetLeft   + par.offsetWidth  / 2;
                const y1 = par.offsetTop    + par.offsetHeight;  // bottom of card = center of add-btn
                const x2 = child.offsetLeft + child.offsetWidth / 2;
                const y2 = child.offsetTop;
                if ([x1,y1,x2,y2].some(v => !isFinite(v))) continue;
                const my = (y1 + y2) / 2;
                const path = document.createElementNS(NS, "path");
                path.setAttribute("d", `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`);
                path.setAttribute("class", "o_flow_connector");
                svg.appendChild(path);

                // Small dot at incoming end (shows direction, matches reference design)
                const endDot = document.createElementNS(NS, "circle");
                endDot.setAttribute("cx", x2); endDot.setAttribute("cy", y2);
                endDot.setAttribute("r", "4"); endDot.setAttribute("fill", "#818cf8");
                svg.appendChild(endDot);

                // Connector label for trigger answers
                const nd = nodeById[parseInt(child.dataset.id)];
                if (nd?.answers?.length) {
                    const lx = (x1 + x2) / 2, ly = (y1 + y2) / 2;
                    let txt = nd.answers.join(" / ");
                    if (txt.length > 40) txt = txt.slice(0, 37) + "…";
                    const aw = Math.min(txt.length * 6.4 + 18, 260);
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

        card.addEventListener("click", e => {
            if (e.target.closest("button")) return;
            e.stopPropagation();
            this.canvasRef.el?.querySelector(".o_flow_card_selected")
                ?.classList.remove("o_flow_card_selected");
            card.classList.add("o_flow_card_selected");
            this.state.selectedNode = {
                id:                 node.id,
                name:               node.name,
                type:               node.type,
                sequence:           node.sequence,
                preview_html:       node.preview_html,
                answers:            node.answers  || [],
                children:           node.children || [],
                waType:             node.waType,
                headerType:         node.headerType,
                headerText:         node.headerText,
                footer:             node.footer,
                buttons:            node.buttons  || [],
                listBtnText:        node.listBtnText,
                listRows:           node.listRows  || [],
                flowCta:            node.flowCta,
                flowName:           node.flowName,
                answerDataType:     node.answerDataType,
                variableName:       node.variableName,
                variableDataSource: node.variableDataSource,
                variableValue:      node.variableValue,
                sourceStepName:     node.sourceStepName,
                sourceVarName:      node.sourceVarName,
            };
        });

        // ── Header: small icon + editable name + type badge ───────────────────
        const head = document.createElement("div");
        head.className = "o_flow_card_head";

        const typeIcon = document.createElement("span");
        typeIcon.className   = "o_flow_card_type_icon";
        typeIcon.textContent = cfg.icon;

        const nameEl = document.createElement("div");
        nameEl.className       = "o_flow_card_name";
        nameEl.textContent     = node.name || `Step #${node.id}`;
        nameEl.contentEditable = "true";
        nameEl.title           = "Click to rename";
        let origName = nameEl.textContent;
        nameEl.addEventListener("focus",   () => { origName = nameEl.textContent; });
        nameEl.addEventListener("keydown", e => {
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

        const badge = document.createElement("span");
        badge.className = "o_flow_card_badge";
        badge.style.background = cfg.color;
        badge.textContent = cfg.label;

        head.appendChild(typeIcon);
        head.appendChild(nameEl);
        head.appendChild(badge);
        card.appendChild(head);

        // ── White content box: message preview + answer chips + IA buttons ──────
        const hasButtons  = node.waType === "interactive_button" && node.buttons?.length;
        const hasListRows = node.waType === "interactive_list"   && node.listRows?.length;
        const hasContent  = node.preview_html || node.headerType || node.footer ||
                            hasButtons || hasListRows ||
                            node.waType === "interactive_flow";

        if (hasContent) {
            const content = document.createElement("div");
            content.className = "o_flow_card_content";

            const hasBubble = node.headerType || node.preview_html || node.footer ||
                              node.waType === "interactive_flow";
            if (hasBubble) {
                const bubble = document.createElement("div");
                bubble.className = "o_flow_bubble";

                // Header
                if (node.headerType === "text" && node.headerText) {
                    const hdr = document.createElement("div");
                    hdr.className = "o_flow_bubble_header_text";
                    hdr.textContent = node.headerText;
                    bubble.appendChild(hdr);
                } else if (node.headerType === "image") {
                    const hdr = document.createElement("div");
                    hdr.className = "o_flow_bubble_header_media";
                    hdr.innerHTML = `<i class="fa fa-image"></i><span>Image</span>`;
                    bubble.appendChild(hdr);
                } else if (node.headerType === "video") {
                    const hdr = document.createElement("div");
                    hdr.className = "o_flow_bubble_header_media";
                    hdr.innerHTML = `<i class="fa fa-play-circle"></i><span>Video</span>`;
                    bubble.appendChild(hdr);
                } else if (node.headerType === "document") {
                    const hdr = document.createElement("div");
                    hdr.className = "o_flow_bubble_header_doc";
                    hdr.innerHTML = `<i class="fa fa-file-text-o"></i><span>${node.headerText || "Document"}</span>`;
                    bubble.appendChild(hdr);
                }

                // Body
                if (node.preview_html) {
                    const body = document.createElement("div");
                    body.className = "o_flow_bubble_body";
                    body.innerHTML = node.preview_html;
                    body.querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
                    bubble.appendChild(body);
                }

                // Footer
                if (node.footer) {
                    const ftr = document.createElement("div");
                    ftr.className = "o_flow_bubble_footer";
                    ftr.textContent = node.footer;
                    bubble.appendChild(ftr);
                }

                // Interactive flow CTA button (inside bubble, like WhatsApp renders it)
                if (node.waType === "interactive_flow") {
                    const fsep = document.createElement("div");
                    fsep.className = "o_flow_bubble_flow_sep";
                    bubble.appendChild(fsep);
                    const fcta = document.createElement("div");
                    fcta.className = "o_flow_bubble_flow_cta";
                    fcta.innerHTML = `<span>${node.flowCta || "Open"}</span><i class="fa fa-chevron-right"></i>`;
                    bubble.appendChild(fcta);
                }

                content.appendChild(bubble);
            }

            // Interactive reply buttons preview
            if (hasButtons) {
                const sep = document.createElement("div");
                sep.className = "o_flow_ia_sep";
                content.appendChild(sep);
                for (const label of node.buttons) {
                    const btn = document.createElement("div");
                    btn.className   = "o_flow_ia_btn";
                    btn.textContent = label;
                    content.appendChild(btn);
                }
            }

            // Interactive list preview
            if (hasListRows) {
                const sep = document.createElement("div");
                sep.className = "o_flow_ia_sep";
                content.appendChild(sep);
                const listBtn = document.createElement("div");
                listBtn.className = "o_flow_ia_list_btn";
                listBtn.innerHTML = `<i class="fa fa-list me-1"/>${node.listBtnText}`;
                content.appendChild(listBtn);
                const shown = node.listRows.slice(0, 3);
                for (const row of shown) {
                    const item = document.createElement("div");
                    item.className   = "o_flow_ia_list_row";
                    item.textContent = row;
                    content.appendChild(item);
                }
                if (node.listRows.length > 3) {
                    const more = document.createElement("div");
                    more.className   = "o_flow_ia_list_more";
                    more.textContent = `+${node.listRows.length - 3} more`;
                    content.appendChild(more);
                }
            }

            card.appendChild(content);
        }

        // ── Output dot (replaces + button — click adds a child step) ──────────
        const dot = document.createElement("div");
        dot.className = "o_flow_out_dot";
        dot.title     = "Add next step";
        dot.addEventListener("click", e => {
            e.preventDefault();
            e.stopPropagation();
            this._openCreateDialog(node.id);
        });
        card.appendChild(dot);

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

    _makeCardDraggable(card, nodeId) {
        card.addEventListener("mousedown", e => {
            if (e.button !== 0) return;
            if (e.target.closest("[contenteditable]") || e.target.closest("button")) return;
            card.style.cursor = "grabbing";
            card.style.zIndex = "50";
            const sx = e.clientX, sy = e.clientY;
            const sl = card.offsetLeft,  st = card.offsetTop;
            const onMove = mv => {
                card.style.left = Math.max(0, sl + mv.clientX - sx) + "px";
                card.style.top  = Math.max(0, st + mv.clientY - sy) + "px";
                if (this._drawLinesFn) this._drawLinesFn();
            };
            const onUp = () => {
                card.style.cursor = "";
                card.style.zIndex = "";
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup",   onUp);
                const pos = this._loadPositions();
                pos[nodeId] = { x: card.offsetLeft, y: card.offsetTop };
                this._savePositions(pos);
            };
            window.addEventListener("mousemove", onMove);
            window.addEventListener("mouseup",   onUp);
            e.stopPropagation();
            e.preventDefault();
        });
    }
}

registry.category("actions").add("comm_whatsapp_chatbot.chatbot_flow", ChatbotFlowAction);
