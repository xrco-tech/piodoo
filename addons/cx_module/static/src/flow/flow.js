/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const NODE_W = 190;
const NODE_H = 66;
const COL_GAP = 90;
const ROW_GAP = 26;
const PAD = 24;

export class CxBotFlow extends Component {
    static template = "cx_module.BotFlow";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.botId = this.props.action.params?.bot_id || false;
        this.state = useState({
            loading: true,
            botName: this.props.action.params?.bot_name || "",
            nodes: [],
            edges: [],
            width: 0,
            height: 0,
        });

        onWillStart(() => this.loadFlow());
    }

    async loadFlow() {
        this.state.loading = true;
        try {
            const [bot] = await this.orm.read("comm.bot", [this.botId], ["name", "entry_step_id"]);
            this.state.botName = bot.name;
            const entryId = bot.entry_step_id ? bot.entry_step_id[0] : false;

            const steps = await this.orm.searchRead(
                "comm.bot.step",
                [["bot_id", "=", this.botId]],
                ["name", "kind", "sequence", "next_step_id", "jump_target_step_id"],
                { order: "sequence, id" }
            );
            const options = await this.orm.searchRead(
                "comm.bot.step.option",
                [["bot_id", "=", this.botId]],
                ["step_id", "label", "next_step_id"],
                { order: "step_id, sequence" }
            );

            this._layout(steps, options, entryId);
        } finally {
            this.state.loading = false;
        }
    }

    // Column layout: BFS depth from the entry step, ordered by sequence within
    // each column; unreachable steps fall into column 0.
    _layout(steps, options, entryId) {
        const byId = new Map(steps.map((s) => [s.id, s]));

        // Collect edges (source id -> {target, label}).
        const edges = [];
        const addEdge = (src, tgt, label) => {
            if (tgt && byId.has(tgt)) {
                edges.push({ src, tgt, label: label || "" });
            }
        };
        for (const s of steps) {
            addEdge(s.id, s.next_step_id && s.next_step_id[0], "");
            addEdge(s.id, s.jump_target_step_id && s.jump_target_step_id[0], "jump");
        }
        for (const o of options) {
            addEdge(o.step_id[0], o.next_step_id && o.next_step_id[0], o.label);
        }

        // BFS depth from entry.
        const depth = new Map();
        const queue = [];
        if (entryId && byId.has(entryId)) {
            depth.set(entryId, 0);
            queue.push(entryId);
        }
        const adj = new Map();
        for (const e of edges) {
            if (!adj.has(e.src)) adj.set(e.src, []);
            adj.get(e.src).push(e.tgt);
        }
        while (queue.length) {
            const id = queue.shift();
            const d = depth.get(id);
            for (const tgt of adj.get(id) || []) {
                if (!depth.has(tgt)) {
                    depth.set(tgt, d + 1);
                    queue.push(tgt);
                }
            }
        }

        // Assign positions column by column.
        const cols = new Map();
        for (const s of steps) {
            const d = depth.has(s.id) ? depth.get(s.id) : 0;
            if (!cols.has(d)) cols.set(d, []);
            cols.get(d).push(s);
        }
        const pos = new Map();
        const nodes = [];
        let maxY = 0;
        for (const [d, colSteps] of [...cols.entries()].sort((a, b) => a[0] - b[0])) {
            colSteps.forEach((s, row) => {
                const x = PAD + d * (NODE_W + COL_GAP);
                const y = PAD + row * (NODE_H + ROW_GAP);
                pos.set(s.id, { x, y });
                maxY = Math.max(maxY, y + NODE_H);
                nodes.push({
                    id: s.id, name: s.name, kind: s.kind, x, y,
                    isEntry: s.id === entryId,
                });
            });
        }

        // Build bezier path strings between node edges.
        const drawn = edges.map((e) => {
            const a = pos.get(e.src);
            const b = pos.get(e.tgt);
            if (!a || !b) return null;
            const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
            const x2 = b.x, y2 = b.y + NODE_H / 2;
            const mx = (x1 + x2) / 2;
            return {
                d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`,
                label: e.label,
                lx: mx, ly: (y1 + y2) / 2 - 4,
            };
        }).filter(Boolean);

        const maxCol = Math.max(0, ...[...cols.keys()]);
        this.state.nodes = nodes;
        this.state.edges = drawn;
        this.state.width = PAD * 2 + (maxCol + 1) * NODE_W + maxCol * COL_GAP;
        this.state.height = maxY + PAD;
    }

    openStep(stepId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "comm.bot.step",
            res_id: stepId,
            views: [[false, "form"]],
            target: "new",
        });
    }
}

registry.category("actions").add("cx_module_bot_flow", CxBotFlow);
