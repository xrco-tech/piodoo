/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

// Step type styling — mirrors comm_whatsapp_chatbot's TYPE_CFG palette
// but keyed on our comm.bot.step.kind values.
const TYPE_CFG = {
    message:        { icon: "💬", label: "Message",     color: "#1a73e8", bg: "#e8f0fe", border: "#93c5fd" },
    menu:           { icon: "🔘", label: "Menu",        color: "#f57c00", bg: "#fff3e0", border: "#fdb57a" },
    input:          { icon: "✏️", label: "Input",       color: "#7c3aed", bg: "#f5f3ff", border: "#c4b5fd" },
    condition:      { icon: "❓", label: "Condition",   color: "#be185d", bg: "#fce4ec", border: "#f9a8d4" },
    action:         { icon: "⚡", label: "Action",      color: "#00796b", bg: "#e0f2f1", border: "#4db6ac" },
    handoff:        { icon: "🎧", label: "Handoff",     color: "#f9a825", bg: "#fff9c4", border: "#fdd835" },
    llm:            { icon: "🧠", label: "LLM",         color: "#388e3c", bg: "#e8f5e9", border: "#81c784" },
    jump:           { icon: "🔀", label: "Jump",        color: "#8e24aa", bg: "#f3e5f5", border: "#ce93d8" },
    wait:           { icon: "⏳", label: "Wait",        color: "#546e7a", bg: "#eceff1", border: "#90a4ae" },
    end:            { icon: "✅", label: "End",         color: "#388e3c", bg: "#c8e6c9", border: "#66bb6a" },
    channel_switch: { icon: "🔁", label: "Channel switch", color: "#0288d1", bg: "#e1f5fe", border: "#4fc3f7" },
};
const DEFAULT_CFG = { icon: "●", label: "Step", color: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" };

// Reingold-Tilford column layout (copied from comm_whatsapp_chatbot)
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
        out.push({
            id: n.id, name: n.name, kind: n.kind,
            level, parent, _col: n._col,
            preview: n.preview || "",
            options: n.options || [],
            body: n.body || "",
            input_type: n.input_type, save_to: n.save_to,
            llm_model: n.llm_model, llm_output_mode: n.llm_output_mode,
            children: n.children,
        });
        flattenTree(n.children || [], level + 1, n.id, out);
    }
    return out;
}

export class BotFlowAction extends Component {
    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvasRef = useRef("canvas");
        this.gridRef = useRef("grid");
        this.svgRef = useRef("svg");

        this.state = useState({
            loading: true,
            botId: null,
            botName: "",
            channels: [],
            variables: [],
            nodes: [],           // flattened tree
            selectedStepId: null,
            zoom: 1.0,
            panelVisible: true,
            panelMode: "props",  // props | sim
            sim: {
                started: false,
                loading: false,
                personaName: "Test User",
                personaMobile: "+27600000001",
                channel: "whatsapp",
                spendRealLlmTokens: false,
                messages: [],
                waiting: "none",   // none | menu | input | done
                currentStepId: null,
                currentOptions: [],
                userInput: "",
                spentUsd: 0.0,
                sessionId: null,
                variables: {},
            },
        });

        onMounted(() => this._loadFlow());
        onPatched(() => this._drawEdges());
    }

    // ── Data loading ────────────────────────────────────────────────
    async _loadFlow() {
        const botId = this.props.action.context.active_id
                    || this.props.action.context.default_bot_id;
        if (!botId) {
            this.notification.add("No bot ID in action context.",
                                  { type: "danger" });
            return;
        }
        this.state.botId = botId;
        this.state.loading = true;
        try {
            const data = await rpc("/comm_chatbot/bot_flow/tree", { bot_id: botId });
            this.state.botName = data.bot_name;
            this.state.channels = data.channels || [];
            this.state.variables = data.variables || [];
            if (data.channels && data.channels.length && !this.state.sim.channel) {
                this.state.sim.channel = data.channels[0].code;
            }
            this._buildLayout(data.tree || []);
        } catch (e) {
            this.notification.add("Failed to load flow: " + e.message,
                                  { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    _buildLayout(tree) {
        _colCtr = 0;
        assignCols(tree);
        this.state.nodes = flattenTree(tree);
    }

    // ── Selection + navigation ─────────────────────────────────────
    _selectStep(nodeId) {
        this.state.selectedStepId = nodeId;
        this.state.panelMode = "props";
    }

    _openStepForm(nodeId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "comm.bot.step",
            res_id: nodeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    _goBack() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "comm.bot",
            res_id: this.state.botId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    _setZoom(zoom) {
        this.state.zoom = Math.max(0.3, Math.min(2.0, zoom));
    }

    get zoomLabel() {
        return Math.round(this.state.zoom * 100) + "%";
    }

    _togglePanel() {
        this.state.panelVisible = !this.state.panelVisible;
    }

    _setPanelMode(mode) {
        this.state.panelMode = mode;
    }

    // ── Node rendering helpers ─────────────────────────────────────
    _typeCfg(kind) {
        return TYPE_CFG[kind] || DEFAULT_CFG;
    }

    _nodePosStyle(node) {
        const col = node._col ?? 0;
        const row = node.level ?? 0;
        const left = col * this._colWidth() + 20;
        const top = row * this._rowHeight() + 20;
        return `left:${left}px;top:${top}px;`;
    }

    _colWidth() { return 260; }
    _rowHeight() { return 150; }

    _gridWidth() {
        const maxCol = this.state.nodes.reduce(
            (m, n) => Math.max(m, n._col ?? 0), 0);
        return (maxCol + 1) * this._colWidth() + 60;
    }
    _gridHeight() {
        const maxRow = this.state.nodes.reduce(
            (m, n) => Math.max(m, n.level ?? 0), 0);
        return (maxRow + 1) * this._rowHeight() + 60;
    }

    _drawEdges() {
        const svg = this.svgRef.el;
        const grid = this.gridRef.el;
        if (!svg || !grid) return;
        const w = this._gridWidth();
        const h = this._gridHeight();
        svg.setAttribute("width", w);
        svg.setAttribute("height", h);
        svg.style.width = w + "px";
        svg.style.height = h + "px";
        svg.innerHTML = "";
        const NS = "http://www.w3.org/2000/svg";

        // Look up cards by data-id for exact positioning
        const cards = grid.querySelectorAll(".o_bf_card");
        const cardById = {};
        cards.forEach(c => { cardById[c.dataset.id] = c; });

        for (const node of this.state.nodes) {
            if (!node.parent) continue;
            const parent = cardById[String(node.parent)];
            const child  = cardById[String(node.id)];
            if (!parent || !child) continue;

            const px = parent.offsetLeft + parent.offsetWidth / 2;
            const py = parent.offsetTop  + parent.offsetHeight;
            const cx = child.offsetLeft  + child.offsetWidth / 2;
            const cy = child.offsetTop;
            const midY = (py + cy) / 2;

            const path = document.createElementNS(NS, "path");
            path.setAttribute("d",
                `M${px},${py} C${px},${midY} ${cx},${midY} ${cx},${cy}`);
            path.setAttribute("class", "o_bf_connector");
            svg.appendChild(path);

            // Small arrow head at the child end
            const dot = document.createElementNS(NS, "circle");
            dot.setAttribute("cx", cx);
            dot.setAttribute("cy", cy);
            dot.setAttribute("r", 3);
            dot.setAttribute("fill", "#9ca3b8");
            svg.appendChild(dot);
        }
    }

    _selectedStep() {
        if (!this.state.selectedStepId) return null;
        return this.state.nodes.find(n => n.id === this.state.selectedStepId);
    }

    // ── Simulator ──────────────────────────────────────────────────
    async _startSim() {
        this.state.sim.loading = true;
        try {
            const data = await rpc("/comm_chatbot/bot_flow/simulate/start", {
                bot_id: this.state.botId,
                channel_code: this.state.sim.channel,
                persona_name: this.state.sim.personaName,
                persona_mobile: this.state.sim.personaMobile,
                spend_real_llm_tokens: this.state.sim.spendRealLlmTokens,
                variables: this.state.sim.variables,
            });
            this.state.sim.sessionId = data.session_id;
            this.state.sim.started = true;
            this._applySimResponse(data);
        } catch (e) {
            this.notification.add("Simulator start failed: " + e.message,
                                  { type: "danger" });
        } finally {
            this.state.sim.loading = false;
        }
    }

    async _sendSimReply() {
        if (!this.state.sim.sessionId) return;
        this.state.sim.loading = true;
        const input = this.state.sim.userInput || "";
        try {
            const data = await rpc("/comm_chatbot/bot_flow/simulate/reply", {
                session_id: this.state.sim.sessionId,
                user_input: input,
            });
            this._applySimResponse(data);
            this.state.sim.userInput = "";
        } catch (e) {
            this.notification.add("Simulator reply failed: " + e.message,
                                  { type: "danger" });
        } finally {
            this.state.sim.loading = false;
        }
    }

    async _resetSim() {
        if (this.state.sim.sessionId) {
            try {
                await rpc("/comm_chatbot/bot_flow/simulate/reset", {
                    session_id: this.state.sim.sessionId,
                });
            } catch (e) { /* ignore */ }
        }
        this.state.sim.started = false;
        this.state.sim.sessionId = null;
        this.state.sim.messages = [];
        this.state.sim.waiting = "none";
        this.state.sim.currentStepId = null;
        this.state.sim.currentOptions = [];
        this.state.sim.userInput = "";
        this.state.sim.spentUsd = 0.0;
    }

    _applySimResponse(data) {
        if (data.messages) {
            this.state.sim.messages = data.messages;
        }
        this.state.sim.waiting = data.waiting || "none";
        this.state.sim.currentStepId = data.current_step_id || null;
        this.state.sim.currentOptions = data.current_options || [];
        this.state.sim.spentUsd = data.spent_usd || 0.0;
        if (data.current_step_id) {
            this._selectStep(data.current_step_id);
        }
    }
}

BotFlowAction.template = "comm_chatbot.BotFlowAction";
BotFlowAction.props = {
    "*": true,   // Odoo 18 injects action / actionId / updateActionState / className
};

registry.category("actions").add("comm_chatbot.bot_flow", BotFlowAction);
