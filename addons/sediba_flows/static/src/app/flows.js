/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODEL = "sediba.flows";

// Card and gap sizes of the canvas, in px. The layout is worked out from
// these alone, so no card has to be measured.
const CARD_W = 220;
const CARD_H = 88;
const GAP_X = 40;
const GAP_Y = 64;
const PAD = 32;

const KINDS = [
    ["message", _t("Message"), "fa-comment-o"],
    ["menu", _t("Menu"), "fa-list-ul"],
    ["input", _t("Question"), "fa-question-circle-o"],
    ["condition", _t("Condition"), "fa-code-fork"],
    ["action", _t("Action"), "fa-bolt"],
    ["llm", _t("AI reply"), "fa-magic"],
    ["handoff", _t("Hand-over"), "fa-user-o"],
    ["jump", _t("Go to flow"), "fa-share"],
    ["wait", _t("Wait"), "fa-clock-o"],
    ["end", _t("End"), "fa-check-circle-o"],
    ["channel_switch", _t("Switch channel"), "fa-exchange"],
];
const KIND = Object.fromEntries(KINDS.map(([key, label, icon]) => [key, { label, icon }]));

const STATUS = {
    draft: _t("Draft"),
    shadow: _t("Test only"),
    live: _t("Live"),
    paused: _t("Paused"),
};

const INPUT_TYPES = [
    ["text", _t("Any text")],
    ["number", _t("A number")],
    ["date", _t("A date")],
    ["email", _t("An email address")],
    ["phone", _t("A phone number")],
    ["media", _t("A photo or file")],
];

const BRANCHING = ["menu", "condition"];
// Kinds with a text the contact reads or hears.
const SPEAKS = ["message", "menu", "input"];
// Kinds followed by one "then" step.
const HAS_THEN = ["message", "input", "action", "llm", "wait", "jump", "channel_switch"];

/** Where each step leads, with the answer that leads there, if any. */
function leadsTo(step) {
    if (BRANCHING.includes(step.kind)) {
        return step.options
            .filter((o) => o.next_id)
            .map((o) => ({
                id: o.next_id,
                label: step.kind === "condition" ? (o.is_default ? _t("otherwise") : _t("if so")) : o.label,
            }));
    }
    const next = step.kind === "jump" ? step.jump_step_id || step.next_id : step.next_id;
    return next ? [{ id: next, label: "" }] : [];
}

/**
 * Place the steps as a tree that starts at the first step. A step that is
 * reached a second time is not drawn twice: the card that leads back to it
 * says so in words. Steps nothing leads to sit beside the tree.
 */
export function layoutFlow(steps, entryId) {
    const byId = Object.fromEntries(steps.map((s) => [s.id, s]));
    const seen = new Set();
    const make = (id, level, label) => {
        seen.add(id);
        const node = { step: byId[id], level, label, kids: [], back: [] };
        for (const target of leadsTo(byId[id])) {
            if (!byId[target.id]) {
                continue;
            }
            if (seen.has(target.id)) {
                node.back.push(byId[target.id].name);
            } else {
                node.kids.push(make(target.id, level + 1, target.label));
            }
        }
        return node;
    };
    const roots = [];
    if (entryId && byId[entryId]) {
        roots.push(make(entryId, 0, ""));
    }
    const targeted = new Set(steps.flatMap((s) => leadsTo(s).map((t) => t.id)));
    for (const pass of [(s) => !targeted.has(s.id), () => true]) {
        for (const step of steps) {
            if (!seen.has(step.id) && pass(step)) {
                roots.push(make(step.id, 0, ""));
            }
        }
    }
    let column = 0;
    const place = (node) => {
        if (!node.kids.length) {
            node.col = column++;
        } else {
            node.kids.forEach(place);
            node.col = (node.kids[0].col + node.kids[node.kids.length - 1].col) / 2;
        }
    };
    roots.forEach(place);

    const nodes = [];
    const edges = [];
    let deepest = 0;
    const walk = (node, parent) => {
        node.x = PAD + node.col * (CARD_W + GAP_X);
        node.y = PAD + node.level * (CARD_H + GAP_Y);
        deepest = Math.max(deepest, node.level);
        nodes.push(node);
        if (parent) {
            const x1 = parent.x + CARD_W / 2;
            const y1 = parent.y + CARD_H;
            const x2 = node.x + CARD_W / 2;
            const y2 = node.y;
            const mid = (y1 + y2) / 2;
            edges.push({
                key: `${parent.step.id}-${node.step.id}`,
                path: `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2 - 3}`,
                label: node.label,
                labelStyle: `left:${x2 - CARD_W / 2}px;top:${y2 - 26}px;width:${CARD_W}px;`,
            });
        }
        node.kids.forEach((kid) => walk(kid, node));
    };
    roots.forEach((root) => walk(root, null));
    return {
        nodes,
        edges,
        width: PAD * 2 + Math.max(column, 1) * (CARD_W + GAP_X) - GAP_X,
        height: PAD * 2 + (deepest + 1) * (CARD_H + GAP_Y) - GAP_Y,
    };
}

function toId(value) {
    const n = Number(value);
    return value && !Number.isNaN(n) ? n : false;
}

export class SedibaFlows extends Component {
    static template = "sediba_flows.App";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.KINDS = KINDS;
        this.INPUT_TYPES = INPUT_TYPES;
        this.edits = 0;
        this.state = useState({
            view: "home",
            home: null,
            data: null,
            selectedId: false,
            draft: null,
            flowName: "",
            showAs: "all",
            panel: "step",
            zoom: 1,
            wording: false,
            sim: this.freshSim(),
        });
        onWillStart(() => this.loadHome());
        onWillUnmount(() => this.simReset());
    }

    // ── Home ─────────────────────────────────────────────────────────────

    async loadHome() {
        this.state.home = await this.orm.call(MODEL, "home", []);
    }

    statusLabel(status) {
        return STATUS[status] || status;
    }

    async newFlow() {
        const id = await this.orm.call(MODEL, "create_flow", []);
        await this.openFlow(id);
    }

    async openFlow(id) {
        this.setData(await this.orm.call(MODEL, "load", [id]), false);
        this.state.showAs = "all";
        this.state.panel = "step";
        this.state.zoom = 1;
        this.state.sim = this.freshSim();
        this.state.view = "builder";
    }

    async backHome() {
        await this.simReset();
        await this.loadHome();
        this.state.view = "home";
        this.state.data = null;
    }

    // ── Builder: data ────────────────────────────────────────────────────

    /** Take a fresh copy of the flow; `select` is the step to show in the panel. */
    setData(data, select) {
        this.state.data = data;
        this.state.flowName = data.flow.name;
        const step = data.steps.find((s) => s.id === select);
        this.state.selectedId = step ? step.id : false;
        this.state.draft = step ? JSON.parse(JSON.stringify(step)) : null;
        this.state.wording = Boolean(step && step.overrides.some((o) => o.body || o.hide));
    }

    get canEdit() {
        return this.state.data.can_edit;
    }

    get flowChannels() {
        const ids = this.state.data.flow.channel_ids;
        return this.state.data.channels.filter((c) => ids.includes(c.id));
    }

    get layout() {
        return layoutFlow(this.state.data.steps, this.state.data.flow.entry_id);
    }

    get canvasStyle() {
        const { width, height } = this.layout;
        return `width:${width}px;height:${height}px;transform:scale(${this.state.zoom});`;
    }

    get zoomLabel() {
        return `${Math.round(this.state.zoom * 100)}%`;
    }

    setZoom(delta) {
        this.state.zoom = Math.min(1.6, Math.max(0.5, Math.round((this.state.zoom + delta) * 10) / 10));
    }

    kindLabel(kind) {
        return KIND[kind] ? KIND[kind].label : kind;
    }

    kindIcon(kind) {
        return `fa ${KIND[kind] ? KIND[kind].icon : "fa-circle-o"}`;
    }

    cardStyle(node) {
        return `left:${node.x}px;top:${node.y}px;width:${CARD_W}px;height:${CARD_H}px;`;
    }

    cardClass(node) {
        const step = node.step;
        let cls = `o_sfl_card o_sfl_kind_${step.kind}`;
        if (step.id === this.state.selectedId) {
            cls += " o_sfl_selected";
        }
        if (this.outState(step) === "skip") {
            cls += " o_sfl_skipped";
        }
        return cls;
    }

    /** One line under the step's name: what it says, as the chosen channel shows it. */
    cardText(step) {
        const code = this.state.showAs;
        if (code !== "all") {
            const out = step.out[code];
            return out ? out.body || out.how : "";
        }
        if (SPEAKS.includes(step.kind)) {
            return step.body;
        }
        if (step.kind === "handoff") {
            return step.handoff_message;
        }
        if (step.kind === "condition") {
            return step.condition;
        }
        if (step.kind === "llm") {
            return step.llm_prompt;
        }
        return "";
    }

    /** "warn" when a channel cannot show the step as written, "skip" when it is left out. */
    outState(step) {
        const code = this.state.showAs;
        const outs = code === "all" ? Object.values(step.out) : [step.out[code]].filter(Boolean);
        if (code !== "all" && outs.length && outs[0].state === "skip") {
            return "skip";
        }
        return outs.some((o) => o.state === "warn") ? "warn" : "ok";
    }

    select(id) {
        const step = this.state.data.steps.find((s) => s.id === id);
        this.state.selectedId = step ? step.id : false;
        this.state.draft = step ? JSON.parse(JSON.stringify(step)) : null;
        this.state.wording = Boolean(step && step.overrides.some((o) => o.body || o.hide));
        this.state.panel = "step";
    }

    otherSteps(id) {
        return this.state.data.steps.filter((s) => s.id !== id);
    }

    // ── Builder: saving ──────────────────────────────────────────────────

    /** Any typing in the panel; a save that comes back older than this is not shown over it. */
    touch() {
        this.edits++;
    }

    async apply(method, args, select) {
        const mark = this.edits;
        const data = await this.orm.call(MODEL, method, args);
        if (mark !== this.edits) {
            // Typed again meanwhile: keep what is on screen, refresh the canvas only.
            this.state.data = data;
            return data;
        }
        this.setData(data, select === undefined ? this.state.selectedId : select);
        return data;
    }

    async saveStep() {
        const d = this.state.draft;
        if (!d || !this.canEdit) {
            return;
        }
        await this.apply("save_step", [
            d.id,
            {
                name: d.name,
                kind: d.kind,
                body: d.body,
                next_id: d.next_id,
                options: d.options,
                input_type: d.input_type,
                save_to: d.save_to,
                condition: d.condition,
                handoff_message: d.handoff_message,
                jump_bot_id: d.jump_bot_id,
                jump_step_id: d.jump_step_id,
                wait_seconds: Number(d.wait_seconds) || 0,
                end_outcome: d.end_outcome,
                llm_prompt: d.llm_prompt,
                llm_use_sediba: d.llm_use_sediba,
                overrides: d.overrides,
            },
        ]);
    }

    setField(name, value, isId) {
        this.touch();
        this.state.draft[name] = isId ? toId(value) : value;
        return this.saveStep();
    }

    setOption(option, name, value, isId) {
        this.touch();
        option[name] = isId ? toId(value) : value;
        return this.saveStep();
    }

    setHide(row, hide) {
        this.touch();
        row.hide = hide;
        return this.saveStep();
    }

    addChoice() {
        this.touch();
        this.state.draft.options.push({ id: false, label: "", next_id: false, is_default: false });
    }

    removeChoice(index) {
        this.touch();
        this.state.draft.options.splice(index, 1);
        return this.saveStep();
    }

    /** A condition has two ways out, kept as two answers: "if so" and "otherwise". */
    branch(isDefault) {
        return this.state.draft.options.find((o) => o.is_default === isDefault);
    }

    setBranch(isDefault, value) {
        this.touch();
        let option = this.branch(isDefault);
        if (!option) {
            option = { id: false, label: isDefault ? _t("Otherwise") : _t("If so"), next_id: false, is_default: isDefault };
            this.state.draft.options.push(option);
        }
        option.next_id = toId(value);
        return this.saveStep();
    }

    async addStep(afterId, optionId) {
        this.edits++;
        const data = await this.orm.call(MODEL, "add_step", [
            this.state.data.flow.id,
            afterId || false,
            optionId || false,
        ]);
        this.setData(data, data.new_id);
        this.state.panel = "step";
    }

    addStepFromToolbar() {
        const d = this.state.draft;
        return this.addStep(d && HAS_THEN.includes(d.kind) ? d.id : false, false);
    }

    deleteStep() {
        const d = this.state.draft;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete this step?"),
            body: _t("“%s” is removed. Whatever led to it will lead to the step after it.", d.name),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                this.edits++;
                this.setData(await this.orm.call(MODEL, "delete_step", [d.id]), false);
            },
            cancel: () => {},
        });
    }

    moreSettings() {
        const id = this.state.draft.id;
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "comm.bot.step",
                res_id: id,
                views: [[false, "form"]],
                target: "new",
            },
            {
                onClose: async () => {
                    this.edits++;
                    this.setData(await this.orm.call(MODEL, "load", [this.state.data.flow.id]), id);
                },
            }
        );
    }

    // ── Builder: the flow itself ─────────────────────────────────────────

    async saveFlow(vals) {
        this.edits++;
        this.setData(
            await this.orm.call(MODEL, "save_flow", [this.state.data.flow.id, vals]),
            this.state.selectedId
        );
        if (this.state.showAs !== "all" && !this.flowChannels.some((c) => c.code === this.state.showAs)) {
            this.state.showAs = "all";
        }
    }

    renameFlow() {
        const name = this.state.flowName.trim();
        if (!name) {
            this.state.flowName = this.state.data.flow.name;
            return;
        }
        if (name !== this.state.data.flow.name) {
            return this.saveFlow({ name });
        }
    }

    toggleChannel(id) {
        const ids = this.state.data.flow.channel_ids;
        return this.saveFlow({
            channel_ids: ids.includes(id) ? ids.filter((c) => c !== id) : [...ids, id],
        });
    }

    get isLive() {
        return this.state.data.flow.status === "live";
    }

    toggleLive() {
        if (this.isLive) {
            return this.saveFlow({ status: "paused" });
        }
        const names = this.flowChannels.map((c) => c.name).join(", ");
        this.dialog.add(ConfirmationDialog, {
            title: _t("Go live?"),
            body: names
                ? _t("From now on this flow answers real contacts on: %s.", names)
                : _t("This flow has no channel yet. Choose at least one first."),
            confirmLabel: _t("Go live"),
            confirm: () => this.saveFlow({ status: "live" }),
            cancel: () => {},
        });
    }

    // ── Try it ───────────────────────────────────────────────────────────

    freshSim() {
        return { channel: "", session: false, messages: [], waiting: "none", options: [], input: "", busy: false, error: "" };
    }

    openTry() {
        this.state.panel = "try";
        const sim = this.state.sim;
        if (!sim.channel || !this.flowChannels.some((c) => c.code === sim.channel)) {
            sim.channel = this.flowChannels.length ? this.flowChannels[0].code : "";
        }
    }

    simTake(res) {
        const sim = this.state.sim;
        sim.busy = false;
        if (res.error) {
            sim.error = res.error;
            return;
        }
        sim.error = "";
        sim.session = res.session_id;
        sim.messages = res.messages;
        sim.waiting = res.waiting;
        sim.options = res.current_options || [];
    }

    async simStart() {
        await this.simReset();
        const sim = this.state.sim;
        if (!sim.channel) {
            return;
        }
        sim.busy = true;
        this.simTake(
            await rpc("/comm_chatbot/bot_flow/simulate/start", {
                bot_id: this.state.data.flow.id,
                channel_code: sim.channel,
                persona_name: "Test contact",
                persona_mobile: "+27600000000",
            })
        );
    }

    async simSend(text) {
        const sim = this.state.sim;
        const body = (text === undefined ? sim.input : text).trim();
        if (!body || !sim.session || sim.busy) {
            return;
        }
        sim.input = "";
        sim.busy = true;
        this.simTake(
            await rpc("/comm_chatbot/bot_flow/simulate/reply", {
                session_id: sim.session,
                user_input: body,
            })
        );
    }

    simKey(ev) {
        if (ev.key === "Enter") {
            this.simSend();
        }
    }

    async simReset() {
        const sim = this.state.sim;
        if (sim.session) {
            const session = sim.session;
            sim.session = false;
            await rpc("/comm_chatbot/bot_flow/simulate/reset", { session_id: session });
        }
        sim.messages = [];
        sim.waiting = "none";
        sim.options = [];
        sim.error = "";
    }
}

registry.category("actions").add("sediba_flows", SedibaFlows);
