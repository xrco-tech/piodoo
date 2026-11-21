/** @odoo-module **/

import { Component, markup, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { escape as escapeHTML } from "@web/core/utils/strings";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODEL = "sediba.flows";

// Card and gap sizes of the canvas, in px. The layout is worked out from
// these alone, so no card has to be measured.
const CARD_W = 220;
const CARD_H = 110;
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
    ["set_variable", _t("Set variable"), "fa-pencil-square-o"],
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

// Frames the Device tab can show the web chat widget in.
const DEVICES = [
    ["iphone", _t("iPhone")],
    ["pixel", _t("Pixel")],
    ["ipad", _t("iPad")],
    ["desktop", _t("Desktop")],
];

const BRANCHING = ["menu", "condition"];
// Kinds with a text the contact reads or hears.
const SPEAKS = ["message", "menu", "input"];
// Kinds followed by one "then" step.
const HAS_THEN = ["message", "input", "action", "llm", "wait", "jump", "channel_switch", "set_variable"];

/** Where each step leads, with the answer that leads there, if any. */
function leadsTo(step) {
    if (BRANCHING.includes(step.kind)) {
        return step.options
            .filter((o) => o.next_id)
            .map((o) => ({
                id: o.next_id,
                label:
                    step.kind !== "condition"
                        ? o.label
                        : o.is_default
                          ? _t("otherwise")
                          : step.condition_mode === "equals"
                            ? o.label
                            : _t("if so"),
            }));
    }
    // A jump inside this flow goes to its target; a jump into another flow
    // either never comes back, or comes back to the step after it.
    let next = step.next_id;
    if (step.kind === "jump") {
        next = step.jump_bot_id ? (step.jump_return ? step.next_id : false) : step.jump_step_id || step.next_id;
    }
    return next ? [{ id: next, label: step.kind === "jump" && step.jump_bot_id ? _t("when it ends") : "" }] : [];
}

/**
 * Place the steps as a tree that starts at the first step. A step that is
 * reached a second time is not drawn twice: the card that leads back to it
 * says so in words. Steps nothing leads to sit beside the tree. A card that
 * was dragged keeps its place; `drag` is the card being dragged right now.
 */
export function layoutFlow(steps, entryId, drag) {
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
    let deepest = 0;
    const walk = (node, parent) => {
        node.parent = parent;
        node.x = PAD + node.col * (CARD_W + GAP_X);
        node.y = PAD + node.level * (CARD_H + GAP_Y);
        // A card that was dragged stays where it was put.
        if (node.step.placed) {
            node.x = node.step.x;
            node.y = node.step.y;
        }
        if (drag && drag.id === node.step.id) {
            node.x = drag.x;
            node.y = drag.y;
        }
        deepest = Math.max(deepest, node.level);
        nodes.push(node);
        node.kids.forEach((kid) => walk(kid, node));
    };
    roots.forEach((root) => walk(root, null));

    const edges = [];
    for (const node of nodes) {
        const parent = node.parent;
        if (!parent) {
            continue;
        }
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
    return {
        nodes,
        edges,
        width: Math.max(...nodes.map((n) => n.x), 0) + CARD_W + PAD,
        height: Math.max(...nodes.map((n) => n.y), 0) + CARD_H + PAD,
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
        this.simInput = useRef("simInput");
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
            // The card being dragged: {id, x, y}.
            drag: null,
            device: "iphone",
            deviceKey: 0,
            busy: false,
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

    /** Copy an older bot into Sediba Flows as a draft, then open the copy. */
    async importLegacy(id) {
        this.state.busy = true;
        try {
            await this.openFlow(await this.orm.call(MODEL, "import_legacy", [id]));
        } finally {
            this.state.busy = false;
        }
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
        return layoutFlow(this.state.data.steps, this.state.data.flow.entry_id, this.state.drag);
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
        if (step.kind === "set_variable") {
            return step.variable_name ? `${step.variable_name} = ${step.variable_value}` : "";
        }
        if (step.kind === "jump" && step.jump_bot_id) {
            const flow = this.state.data.flows.find((f) => f.id === step.jump_bot_id);
            return flow ? flow.name : "";
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

    // ── Usage ────────────────────────────────────────────────────────────

    /** Only steps that say something are counted; the others send nothing to count. */
    hasUsage(step) {
        return ["message", "menu", "input", "handoff", "llm", "channel_switch"].includes(step.kind);
    }

    /** Contacts this step was reached by, as a share of the most-reached step. */
    reachPct(step) {
        const most = this.state.data.flow.reached_most;
        return most ? Math.round((step.reached / most) * 100) : 0;
    }

    /** How many fewer contacts reached this step than the step that leads to it, in %. */
    dropOff(node) {
        const before = node.parent && node.parent.step.reached;
        if (!before || !this.hasUsage(node.parent.step)) {
            return null;
        }
        const pct = Math.round((1 - node.step.reached / before) * 100);
        return pct > 0 ? pct : null;
    }

    usageTitle(node) {
        const drop = this.dropOff(node);
        let title = `${node.step.reached} ${_t("contacts reached this step")}, ${this.reachPct(node.step)}% ${_t("of the most-reached step")}.`;
        if (drop !== null) {
            title += ` ${drop}% ${_t("fewer than the step before")}.`;
        }
        return title;
    }

    // ── Dragging a card ──────────────────────────────────────────────────

    cardDown(ev, node) {
        if (!this.canEdit || ev.button !== 0) {
            return;
        }
        this.dragging = { id: node.step.id, sx: ev.clientX, sy: ev.clientY, ox: node.x, oy: node.y, moved: false };
        ev.currentTarget.setPointerCapture(ev.pointerId);
    }

    cardMove(ev) {
        const d = this.dragging;
        if (!d) {
            return;
        }
        const dx = (ev.clientX - d.sx) / this.state.zoom;
        const dy = (ev.clientY - d.sy) / this.state.zoom;
        // A few pixels of wobble is still a click, not a drag.
        if (!d.moved && Math.hypot(dx, dy) < 5) {
            return;
        }
        d.moved = true;
        this.state.drag = {
            id: d.id,
            x: Math.max(0, Math.round(d.ox + dx)),
            y: Math.max(0, Math.round(d.oy + dy)),
        };
    }

    async cardUp() {
        const d = this.dragging;
        this.dragging = null;
        const place = this.state.drag;
        if (!d || !d.moved || !place) {
            this.state.drag = null;
            return;
        }
        // The click that follows letting go must not select the card.
        this.justDragged = true;
        const step = this.state.data.steps.find((s) => s.id === d.id);
        Object.assign(step, { placed: true, x: place.x, y: place.y });
        this.state.drag = null;
        await this.orm.call(MODEL, "move_step", [d.id, place.x, place.y]);
    }

    cardClick(id) {
        if (this.justDragged) {
            this.justDragged = false;
            return;
        }
        this.select(id);
    }

    get anyPlaced() {
        return this.state.data.steps.some((s) => s.placed);
    }

    async tidy() {
        this.edits++;
        this.setData(await this.orm.call(MODEL, "tidy", [this.state.data.flow.id]), this.state.selectedId);
    }

    // ── Device ───────────────────────────────────────────────────────────

    get devices() {
        return DEVICES;
    }

    openDevice() {
        this.state.panel = "device";
        this.state.deviceKey++;
    }

    pickDevice(key) {
        this.state.device = key;
    }

    /** The preview's address; the counter makes "Start again" load it afresh. */
    get deviceUrl() {
        return `${this.state.data.flow.device_url}&_ts=${this.state.deviceKey}`;
    }

    select(id) {
        const step = this.state.data.steps.find((s) => s.id === id);
        this.state.selectedId = step ? step.id : false;
        this.state.draft = step ? JSON.parse(JSON.stringify(step)) : null;
        this.state.wording = Boolean(step && step.overrides.some((o) => o.body || o.hide));
        this.state.panel = "step";
    }

    /** Which field the panel's "Then" writes: a jump inside this flow keeps its target apart. */
    get thenField() {
        const d = this.state.draft;
        return d.kind === "jump" && !d.jump_bot_id ? "jump_step_id" : "next_id";
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
                condition_mode: d.condition_mode,
                handoff_message: d.handoff_message,
                jump_bot_id: d.jump_bot_id,
                jump_step_id: d.jump_step_id,
                wait_seconds: Number(d.wait_seconds) || 0,
                end_outcome: d.end_outcome,
                llm_prompt: d.llm_prompt,
                llm_use_sediba: d.llm_use_sediba,
                jump_return: d.jump_return,
                variable_name: d.variable_name,
                variable_value: d.variable_value,
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

    /** The values a "which value" condition names, without its "otherwise". */
    get valueBranches() {
        return this.state.draft.options.filter((o) => !o.is_default);
    }

    removeOption(option) {
        this.touch();
        const options = this.state.draft.options;
        options.splice(options.indexOf(option), 1);
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
        return {
            channel: "",
            session: false,
            messages: [],
            waiting: "none",
            options: [],
            input: "",
            busy: false,
            error: "",
            // Who the test contact is, and the variables to start with.
            name: "",
            mobile: "",
            groups: [],
            ready: false,
            editing: false,
        };
    }

    async openTry() {
        this.state.panel = "try";
        const sim = this.state.sim;
        if (!sim.channel || !this.flowChannels.some((c) => c.code === sim.channel)) {
            sim.channel = this.flowChannels.length ? this.flowChannels[0].code : "";
        }
        if (!sim.session) {
            await this.simSetup();
        }
    }

    /** Ask who the test contact is and which variables the flow has. */
    async simSetup() {
        const sim = this.state.sim;
        const setup = await this.orm.call(MODEL, "try_setup", [this.state.data.flow.id]);
        sim.name = setup.name;
        sim.mobile = setup.mobile;
        sim.groups = setup.groups;
        sim.ready = true;
    }

    get simChannelName() {
        const channel = this.flowChannels.find((c) => c.code === this.state.sim.channel);
        return channel ? channel.name : "";
    }

    /** The values typed for the variables, as {name: text}. */
    simValues() {
        const values = {};
        for (const group of this.state.sim.groups) {
            for (const variable of group.variables) {
                values[variable.name] = variable.value;
            }
        }
        return values;
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
        // Show what each variable holds now, so the next change starts from it.
        for (const group of sim.groups) {
            for (const variable of group.variables) {
                variable.value = res.variables[variable.name] ?? "";
            }
        }
    }

    async simStart() {
        const sim = this.state.sim;
        if (!sim.channel || sim.busy) {
            return;
        }
        const values = this.simValues();
        await this.simStop();
        sim.busy = true;
        sim.editing = false;
        this.simTake(
            await this.orm.call(MODEL, "try_start", [
                this.state.data.flow.id,
                sim.channel,
                sim.name,
                sim.mobile,
                values,
            ])
        );
    }

    /** Back to the form that asks who the contact is, with fresh values. */
    async simRestart() {
        await this.simStop();
        await this.simSetup();
    }

    async simApply() {
        const sim = this.state.sim;
        if (!sim.session || sim.busy) {
            return;
        }
        sim.busy = true;
        this.simTake(
            await this.orm.call(MODEL, "try_apply", [sim.session, sim.name, sim.mobile, this.simValues()])
        );
        sim.editing = false;
    }

    async simSend(text) {
        const sim = this.state.sim;
        const body = (text === undefined ? sim.input : text).trim();
        if (!body || !sim.session || sim.busy) {
            return;
        }
        sim.input = "";
        if (this.simInput.el) {
            this.simInput.el.value = "";
        }
        sim.busy = true;
        this.simTake(await this.orm.call(MODEL, "try_reply", [sim.session, body]));
    }

    simKey(ev) {
        if (ev.key === "Enter") {
            this.simSend();
        }
    }

    async simStop() {
        const sim = this.state.sim;
        if (sim.session) {
            const session = sim.session;
            sim.session = false;
            await this.orm.call(MODEL, "try_stop", [session]);
        }
        sim.messages = [];
        sim.waiting = "none";
        sim.options = [];
        sim.error = "";
    }

    // Kept under its first name: leaving the builder calls it.
    simReset() {
        return this.simStop();
    }

    /**
     * A USSD handset shows one screen at a time: what the flow said since the
     * contact's last reply.
     */
    get simScreen() {
        const messages = this.state.sim.messages;
        let from = 0;
        messages.forEach((m, i) => {
            if (m.direction === "inbound") {
                from = i + 1;
            }
        });
        return messages
            .slice(from)
            .map((m) => m.body)
            .join("\n");
    }

    /** WhatsApp shows a menu's choices as buttons, so the numbered list is left out of the text. */
    get simButtons() {
        const sim = this.state.sim;
        return sim.channel === "whatsapp" && sim.waiting === "menu" ? sim.options : [];
    }

    /**
     * The text of one message as its channel shows it. WhatsApp turns *bold*,
     * _italic_, ~strike~ and ```code``` into formatting; every other channel
     * shows the characters as typed.
     */
    simBody(message) {
        const escaped = escapeHTML(message.body || "");
        if (this.state.sim.channel !== "whatsapp") {
            return markup(escaped);
        }
        return markup(
            escaped
                .replace(/```([^`]+)```/g, "<code>$1</code>")
                .replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>")
                .replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?])/g, "$1<em>$2</em>")
                .replace(/~([^~\n]+)~/g, "<s>$1</s>")
        );
    }
}

registry.category("actions").add("sediba_flows", SedibaFlows);
