/** @odoo-module **/

import { Component, markup, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
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
    transfer_to_agent:    { icon: "🎧", label: "Transfer",      color: "#9333ea", bg: "#faf5ff", border: "#d8b4fe" },
    jump_to_flow:         { icon: "🔀", label: "Jump",          color: "#4338ca", bg: "#eef2ff", border: "#a5b4fc" },
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
                   sourceVarName: n.sourceVarName,
                   maxRetries: n.maxRetries, fallbackStepId: n.fallbackStepId,
                   fallbackStepName: n.fallbackStepName,
                   targetChatbotId: n.targetChatbotId,
                   targetChatbotName: n.targetChatbotName,
                   targetStepName: n.targetStepName,
                   jumpMode: n.jumpMode,
                   varMappingCount: n.varMappingCount,
                   msgCount: n.msgCount });
        flattenTree(n.children || [], level + 1, n.id, out);
    }
    return out;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function bodyToHtml(text) {
    if (!text) return "";
    // Escape first so user content can't inject markup.
    let s = String(text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    // WhatsApp formatting markers, in this order:
    //   ```code``` → monospace (apply before single-char markers so we don't
    //                eat backticks mid-rewrite)
    //   *bold*    → <strong>
    //   _italic_  → <em>
    //   ~strike~  → <s>
    s = s.replace(/```([^`\n]+)```/g, "<code>$1</code>");
    s = s.replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>");
    s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");
    s = s.replace(/~([^~\n]+)~/g, "<s>$1</s>");
    return s.replace(/\n/g, "<br>");
}
function plainToHtml(text) {
    // SMS / USSD: just escape + preserve line breaks; no formatting.
    if (!text) return "";
    return String(text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");
}

// ── Client action component ───────────────────────────────────────────────────
export class ChatbotFlowAction extends Component {
    static template = "comm_whatsapp_chatbot.ChatbotFlowAction";
    // Wildcard: Odoo 18 client-action framework injects extra props
    // (updateActionState, className) beyond the ones the widget uses.
    static props = { "*": true };

    setup() {
        this.orm    = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.notification = useService("notification");

        this.chatbotId   = this.props.action.params?.chatbot_id;
        this.canvasRef   = useRef("canvas");
        this._tree         = [];
        this._flat         = [];
        this._msgCounts    = {};
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
            maxCount:     0,
            panelVisible: this._initialPanelVisible(),
            // Right-panel mode: "props" (default) | "sim" (live simulator)
            panelMode:    "props",
            // Simulator state — kept here so it survives re-renders within the session.
            sim: {
                bubbles: [],
                session_state: null,
                userInput: "",
                terminate: false,
                waitForInput: false,
                channel: "whatsapp",
                sending: false,
                started: false,
                // Persona the simulator runs as. Surface a form before
                // starting so authors can demo different contacts.
                personaName: "Sim User",
                personaMobile: "+27600000001",
                // Variables editor — populated by the /chatbot/simulate/setup
                // endpoint. Shape: [{chatbot_id, chatbot_name, is_root,
                // variables: [{id, name, data_type, value}]}, ...].
                setupBots: [],
                setupLoading: false,
                // In-session editor: shows the persona+variables form again
                // over the chat without restarting the flow.
                editorOpen: false,
                editorSaving: false,
            },
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
             "variable_value", "source_step_id", "source_variable_id",
             "max_retries", "fallback_step_id",
             "target_chatbot_id", "target_step_id", "jump_mode", "variable_mapping_ids"],
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

        // Fetch outgoing message counts per step for funnel analysis
        const countGroups = await this.orm.readGroup(
            "whatsapp.chatbot.message",
            [["chatbot_id", "=", this.chatbotId], ["type", "=", "outgoing"],
             ["step_id", "!=", false]],
            ["step_id"],
            ["step_id"],
        );
        this._msgCounts = {};
        for (const g of countGroups) {
            const sid = Array.isArray(g.step_id) ? g.step_id[0] : g.step_id;
            this._msgCounts[sid] = g.__count || g.step_id_count || 0;
        }
        this.state.maxCount = Object.values(this._msgCounts).length
            ? Math.max(...Object.values(this._msgCounts))
            : 0;

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
        const noPreview = new Set(["execute_code", "set_variable", "end_flow", "jump_to_flow"]);
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
            maxRetries:         s.max_retries || 3,
            fallbackStepId:     Array.isArray(s.fallback_step_id) ? s.fallback_step_id[0] : null,
            fallbackStepName:   Array.isArray(s.fallback_step_id) ? s.fallback_step_id[1] : "",
            msgCount:           this._msgCounts[s.id] || 0,
            answerDataType:     s.answer_data_type || "",
            variableName:       Array.isArray(s.variable_id)       ? s.variable_id[1]       : "",
            variableDataSource: s.variable_data_source || "",
            variableValue:      s.variable_value || "",
            sourceStepName:     Array.isArray(s.source_step_id)    ? s.source_step_id[1]    : "",
            sourceVarName:      Array.isArray(s.source_variable_id)? s.source_variable_id[1]: "",
            targetChatbotId:    Array.isArray(s.target_chatbot_id) ? s.target_chatbot_id[0] : null,
            targetChatbotName:  Array.isArray(s.target_chatbot_id) ? s.target_chatbot_id[1] : "",
            targetStepName:     Array.isArray(s.target_step_id)    ? s.target_step_id[1]    : "",
            jumpMode:           s.jump_mode || "one_way",
            varMappingCount:    (s.variable_mapping_ids || []).length,
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

    // ── Properties panel show/hide ───────────────────────────────────────────

    _initialPanelVisible() {
        try {
            const stored = localStorage.getItem("chatbot_flow_panel_visible");
            if (stored === "0") return false;
            if (stored === "1") return true;
        } catch {}
        // No saved preference → default: shown on desktop, hidden on narrow viewports
        return typeof window !== "undefined" ? window.innerWidth >= 768 : true;
    }

    _togglePanel() {
        this.state.panelVisible = !this.state.panelVisible;
        try {
            localStorage.setItem("chatbot_flow_panel_visible",
                                 this.state.panelVisible ? "1" : "0");
        } catch {}
        // Connector lines depend on canvas width — let CSS transition settle, then redraw.
        if (this._drawLinesFn) {
            setTimeout(() => this._drawLinesFn?.(), 280);
        }
    }

    // ── Simulator ─────────────────────────────────────────────────────────

    _setPanelMode(mode) {
        this.state.panelMode = mode;
        // No auto-start — the user picks a persona via the form first.
        // Lazy-load the variable form data the first time the user opens
        // the simulator panel.
        if (mode === "sim" && !this.state.sim.setupBots.length && !this.state.sim.setupLoading) {
            this._simLoadSetup();
        }
    }

    async _simLoadSetup() {
        this.state.sim.setupLoading = true;
        try {
            const data = await rpc("/chatbot/simulate/setup", {
                chatbot_id: this.chatbotId,
                contact_details: {
                    name:   (this.state.sim.personaName || "").trim(),
                    mobile: (this.state.sim.personaMobile || "").trim(),
                },
            });
            this.state.sim.setupBots = data?.bots || [];
            // If the backend found an existing persona, prefill the form.
            const p = data?.persona || {};
            if (p.name)   this.state.sim.personaName   = p.name;
            if (p.mobile) this.state.sim.personaMobile = p.mobile;
        } catch (e) {
            // Non-fatal — the form just shows persona-only.
        } finally {
            this.state.sim.setupLoading = false;
        }
    }

    // Flatten setupBots into the {variable_id, value} list the backend wants.
    _simCollectInitialVariables() {
        const out = [];
        for (const bot of (this.state.sim.setupBots || [])) {
            for (const v of (bot.variables || [])) {
                if (v.value !== "" && v.value !== null && v.value !== undefined) {
                    out.push({ variable_id: v.id, value: v.value });
                }
            }
        }
        return out;
    }

    async _simStart() {
        const name = (this.state.sim.personaName || "").trim();
        const mobile = (this.state.sim.personaMobile || "").trim();
        if (!mobile) {
            this.notification.add("Mobile number is required to start a session.", { type: "warning" });
            return;
        }
        Object.assign(this.state.sim, {
            bubbles: [],
            session_state: null,
            userInput: "",
            terminate: false,
            waitForInput: false,
            sending: true,
            started: true,
        });
        await this._simSendTurn(null);
    }

    _simChangePersona() {
        // Back to the form so the user can change name/mobile or restart fresh.
        Object.assign(this.state.sim, {
            bubbles: [],
            session_state: null,
            userInput: "",
            terminate: false,
            waitForInput: false,
            sending: false,
            started: false,
            editorOpen: false,
        });
    }

    _simToggleEditor() {
        this.state.sim.editorOpen = !this.state.sim.editorOpen;
    }

    async _simApplyEditor() {
        // Push persona + variable edits to the running session without
        // restarting the flow.
        if (this.state.sim.editorSaving) return;
        this.state.sim.editorSaving = true;
        try {
            await rpc("/chatbot/simulate/update", {
                chatbot_id:    this.chatbotId,
                session_state: this.state.sim.session_state,
                contact_details: {
                    name:   (this.state.sim.personaName || "").trim(),
                    mobile: (this.state.sim.personaMobile || "").trim(),
                },
                initial_variables: this._simCollectInitialVariables(),
            });
            this.state.sim.editorOpen = false;
        } catch (e) {
            this.notification.add("Could not apply changes.", { type: "danger" });
        } finally {
            this.state.sim.editorSaving = false;
        }
    }

    async _simSendInput() {
        const txt = (this.state.sim.userInput || "").trim();
        if (!txt || this.state.sim.sending || this.state.sim.terminate) return;
        // Echo the user's input first so the chat reads naturally.
        this.state.sim.bubbles.push({ text: txt, dir: "out", step_type: "user" });
        this.state.sim.userInput = "";
        this.state.sim.sending = true;
        await this._simSendTurn(txt);
    }

    async _simSendTurn(userInput) {
        try {
            const data = await rpc("/chatbot/simulate", {
                chatbot_id:      this.chatbotId,
                session_state:   this.state.sim.session_state,
                user_input:      userInput,
                contact_details: {
                    name:   (this.state.sim.personaName || "").trim(),
                    mobile: (this.state.sim.personaMobile || "").trim(),
                },
                initial_variables: this._simCollectInitialVariables(),
            });
            if (!data) return;
            for (const b of (data.bubbles || [])) {
                // Preserve every field the backend sent — header_type / footer /
                // wa_message_type / buttons / list_rows / flow_cta / channel etc.
                // The template reads these directly. Force dir='in' since the
                // backend never marks bubbles as user-sent.
                this.state.sim.bubbles.push({
                    ...b,
                    dir: "in",
                    text: b.text || b.body || "",
                    step_type: b.step_type || "message",
                });
            }
            this.state.sim.session_state = data.session_state;
            this.state.sim.terminate    = !!data.terminate;
            this.state.sim.waitForInput = !!data.wait_for_input;
            this.state.sim.channel      = data.channel || this.state.sim.channel;
        } catch (e) {
            this.state.sim.bubbles.push({
                text: "Simulator error.",
                dir: "in", step_type: "error",
            });
            this.state.sim.terminate = true;
        } finally {
            this.state.sim.sending = false;
            // Auto-scroll the chat to bottom on next paint.
            queueMicrotask(() => {
                const el = document.querySelector(".o_flow_sim_chat");
                if (el) el.scrollTop = el.scrollHeight;
            });
        }
    }

    _simOnInputKey(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this._simSendInput();
        }
    }

    // Quick-reply: user tapped a button/list row/flow CTA. Send its label
    // as the next user input so the engine routes via trigger_answer_ids.
    async _simSendQuickReply(text) {
        if (!text || this.state.sim.sending || this.state.sim.terminate) return;
        this.state.sim.bubbles.push({ text, dir: "out", step_type: "user" });
        this.state.sim.sending = true;
        await this._simSendTurn(text);
    }

    // Formatters exposed to the OWL template for the simulator bubbles.
    // Wrapped in markup() so OWL's t-out treats the returned strings as HTML
    // instead of escaping them — both helpers already escape user content
    // before injecting their own tags, so they're safe.
    simFormatBody(text, channel) {
        return markup(channel === "whatsapp" ? bodyToHtml(text) : plainToHtml(text));
    }
    simEscape(text) {
        return markup(plainToHtml(text));
    }

    _goBack() {
        // If we navigated in via _openTargetChatbot, the previous chatbot is on
        // our own nav stack — pop it and re-open. Otherwise fall back to browser
        // history (returns to wherever the flow was entered from).
        const navStack = [...(this.props.action.params?.nav_stack || [])];
        if (navStack.length) {
            const prev = navStack.pop();
            this.action.doAction({
                type: "ir.actions.client",
                tag: "comm_whatsapp_chatbot.chatbot_flow",
                name: prev.name || "Chatbot Flow",
                params: {
                    chatbot_id: prev.id,
                    chatbot_name: prev.name || "",
                    nav_stack: navStack,
                },
            });
            return;
        }
        history.back();
    }

    _openTargetChatbot(chatbotId, chatbotName) {
        if (!chatbotId) return;
        const navStack = [...(this.props.action.params?.nav_stack || [])];
        navStack.push({ id: this.chatbotId, name: this.state.chatbotName });
        this.action.doAction({
            type: "ir.actions.client",
            tag: "comm_whatsapp_chatbot.chatbot_flow",
            name: chatbotName || "Chatbot Flow",
            params: {
                chatbot_id: chatbotId,
                chatbot_name: chatbotName || "",
                nav_stack: navStack,
            },
        });
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

    // ── Funnel / reach helpers ────────────────────────────────────────────────

    _statFillColor(ratio) {
        if (ratio >= 0.75) return "#16a34a";
        if (ratio >= 0.50) return "#84cc16";
        if (ratio >= 0.25) return "#f59e0b";
        return "#ef4444";
    }

    reachPct(msgCount) {
        if (!this.state.maxCount) return 0;
        return Math.round((msgCount || 0) / this.state.maxCount * 100);
    }

    reachColor(msgCount) {
        return this._statFillColor((msgCount || 0) / (this.state.maxCount || 1));
    }

    dropOffPct(msgCount, parentId) {
        if (!parentId || !this._msgCounts) return null;
        const parentCount = this._msgCounts[parentId] || 0;
        if (!parentCount || !msgCount) return null;
        const pct = Math.round((1 - msgCount / parentCount) * 100);
        return pct >= 0 ? pct : null;
    }

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

                // Fallback connectors — dashed orange, from question step to fallback step
                for (const src of grid.querySelectorAll(".o_flow_card[data-fallback]")) {
                    const fbEl = byId[src.dataset.fallback]; if (!fbEl) continue;
                    const fx1 = src.offsetLeft  + src.offsetWidth  / 2;
                    const fy1 = src.offsetTop   + src.offsetHeight / 2;
                    const fx2 = fbEl.offsetLeft + fbEl.offsetWidth  / 2;
                    const fy2 = fbEl.offsetTop;
                    if ([fx1,fy1,fx2,fy2].some(v => !isFinite(v))) continue;
                    const fmy = (fy1 + fy2) / 2;
                    const fbPath = document.createElementNS(NS, "path");
                    fbPath.setAttribute("d", `M ${fx1} ${fy1} C ${fx1} ${fmy}, ${fx2} ${fmy}, ${fx2} ${fy2}`);
                    fbPath.setAttribute("class", "o_flow_fallback_connector");
                    svg.appendChild(fbPath);
                    const fbLbl = document.createElementNS(NS, "text");
                    fbLbl.setAttribute("x", (fx1+fx2)/2); fbLbl.setAttribute("y", (fy1+fy2)/2 - 4);
                    fbLbl.setAttribute("text-anchor", "middle");
                    fbLbl.setAttribute("class", "o_flow_fallback_lbl");
                    fbLbl.textContent = "fallback";
                    svg.appendChild(fbLbl);
                }

                // Subroutine return arc: dashed self-loop on the right side of a
                // jump_to_flow subroutine card — signals "callee returns to this card".
                for (const jc of grid.querySelectorAll(".o_flow_card[data-jump-sub]")) {
                    const jx = jc.offsetLeft + jc.offsetWidth;
                    const jy1 = jc.offsetTop + 20;
                    const jy2 = jc.offsetTop + jc.offsetHeight - 20;
                    if ([jx, jy1, jy2].some(v => !isFinite(v))) continue;
                    const arc = document.createElementNS(NS, "path");
                    arc.setAttribute("d", `M ${jx} ${jy1} C ${jx + 38} ${jy1}, ${jx + 38} ${jy2}, ${jx} ${jy2}`);
                    arc.setAttribute("class", "o_flow_jump_arc");
                    svg.appendChild(arc);
                    const arrow = document.createElementNS(NS, "polygon");
                    arrow.setAttribute("points", `${jx - 5},${jy2 - 4} ${jx + 1},${jy2} ${jx - 5},${jy2 + 4}`);
                    arrow.setAttribute("class", "o_flow_jump_arc_head");
                    svg.appendChild(arrow);
                }

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
        const TERMINAL_TYPES = new Set(["end_flow", "transfer_to_agent"]);
        // One-way jumps end the local tree; subroutine jumps return so children are valid.
        const isJumpOneWay = node.type === "jump_to_flow" && node.jumpMode === "one_way";
        const isTerminal = TERMINAL_TYPES.has(node.type) || isJumpOneWay;
        const isDeadEnd = !node.children?.length && !isTerminal;

        card.className  = "o_flow_card" + (isDeadEnd ? " o_flow_card_dead_end" : "");
        card.dataset.id = node.id;
        if (node.parent)          card.dataset.parent   = node.parent;
        if (node.fallbackStepId)  card.dataset.fallback = node.fallbackStepId;
        if (node.type === "jump_to_flow" && node.jumpMode === "subroutine") {
            card.dataset.jumpSub = "1";
        }

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
                isDeadEnd:          isDeadEnd,
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
                maxRetries:         node.maxRetries,
                fallbackStepId:     node.fallbackStepId,
                fallbackStepName:   node.fallbackStepName,
                targetChatbotId:    node.targetChatbotId,
                targetChatbotName:  node.targetChatbotName,
                targetStepName:     node.targetStepName,
                jumpMode:           node.jumpMode,
                varMappingCount:    node.varMappingCount || 0,
                msgCount:           node.msgCount || 0,
                parentId:           node.parent || null,
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

        // ── Jump to Flow/Bot summary block ────────────────────────────────────
        if (node.type === "jump_to_flow") {
            const jumpBox = document.createElement("div");
            jumpBox.className = "o_flow_card_content o_flow_jump_box";

            const targetRow = document.createElement("div");
            targetRow.className = "o_flow_jump_target";
            const safeName = (node.targetChatbotName || "— pick a bot —").replace(/</g, "&lt;");
            targetRow.innerHTML =
                `<i class="fa fa-share o_flow_jump_arrow" aria-hidden="true"/>` +
                `<span class="o_flow_jump_target_name">${safeName}</span>`;
            jumpBox.appendChild(targetRow);

            if (node.targetStepName) {
                const stepRow = document.createElement("div");
                stepRow.className = "o_flow_jump_step";
                stepRow.textContent = "↳ " + node.targetStepName;
                jumpBox.appendChild(stepRow);
            } else {
                const stepRow = document.createElement("div");
                stepRow.className = "o_flow_jump_step text-muted";
                stepRow.textContent = "↳ Root step";
                jumpBox.appendChild(stepRow);
            }

            const modeRow = document.createElement("div");
            modeRow.className = "o_flow_jump_mode " +
                (node.jumpMode === "subroutine" ? "o_flow_jump_mode_sub" : "o_flow_jump_mode_one");
            modeRow.textContent = node.jumpMode === "subroutine"
                ? "↺ Subroutine — returns here"
                : "→ One-way (no return)";
            jumpBox.appendChild(modeRow);

            if (node.varMappingCount) {
                const mapRow = document.createElement("div");
                mapRow.className = "o_flow_jump_map_count text-muted";
                mapRow.textContent = `${node.varMappingCount} variable mapping${node.varMappingCount === 1 ? "" : "s"}`;
                jumpBox.appendChild(mapRow);
            }

            card.appendChild(jumpBox);
        }

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

        // ── Dead-end warning badge ────────────────────────────────────────────
        if (isDeadEnd) {
            const warn = document.createElement("div");
            warn.className = "o_flow_dead_end_badge";
            warn.textContent = "⚠";
            warn.title = "Dead-end: this step has no children and is not a terminal node";
            card.appendChild(warn);
        }

        // ── Message count strip ───────────────────────────────────────────────
        if (this.state.maxCount > 0) {
            const count = node.msgCount || 0;
            const ratio = count / this.state.maxCount;
            const pct   = Math.round(ratio * 100);
            const color = this._statFillColor(ratio);

            const stat = document.createElement("div");
            stat.className = "o_flow_card_stat";

            const countEl = document.createElement("span");
            countEl.className   = "o_flow_card_stat_count";
            countEl.textContent = `👤 ${count.toLocaleString()}`;

            const barWrap = document.createElement("div");
            barWrap.className = "o_flow_card_stat_bar";
            const barFill = document.createElement("div");
            barFill.className        = "o_flow_card_stat_fill";
            barFill.style.width      = `${pct}%`;
            barFill.style.background = color;
            barWrap.appendChild(barFill);

            const pctEl = document.createElement("span");
            pctEl.className   = "o_flow_card_stat_pct";
            pctEl.style.color = color;
            pctEl.textContent = `${pct}%`;

            stat.appendChild(countEl);
            stat.appendChild(barWrap);
            stat.appendChild(pctEl);
            card.appendChild(stat);
        }

        // ── Output dot (replaces + button — click adds a child step) ──────────
        // Skip for terminal nodes (end_flow, transfer_to_agent, one-way jump_to_flow).
        if (!isTerminal) {
            const dot = document.createElement("div");
            dot.className = "o_flow_out_dot";
            dot.title     = "Add next step";
            dot.addEventListener("click", e => {
                e.preventDefault();
                e.stopPropagation();
                this._openCreateDialog(node.id);
            });
            card.appendChild(dot);
        }

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
