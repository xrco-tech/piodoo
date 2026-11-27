/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

/**
 * Flow diagrams inside a company doc: the picture, the block that shows it
 * in a doc, and the editor.
 *
 * A diagram is a list of steps, each saying which step comes next. Nobody
 * draws lines: `layoutFlow` places the steps as a tree, the way the chatbot
 * flow builder does, and draws the lines between them.
 */

export const KINDS = [
    ["start", _t("Start")],
    ["step", _t("Step")],
    ["decision", _t("Decision")],
    ["handover", _t("Hand-over")],
    ["end", _t("End")],
];
const KIND_LABEL = Object.fromEntries(KINDS);

const CARD_W = 220;
const CARD_H = 72;
const COLUMN = 320; // from one column's left edge to the next
const GAP = 48; // between two rows
const GAP_LABELLED = 96; // when the lines below a row carry answers
const PAD = 24;
const LANE = 14; // between two lines that run down the right-hand side
const SMALLEST = 0.65; // a diagram in a doc is never drawn smaller than this; past it, it scrolls

/**
 * Where every step and line goes.
 * Returns { nodes: [{step, number, left, top}], edges: [{d, label, left, top}],
 *           width, height, order: steps in reading order }.
 */
export function layoutFlow(steps) {
    const byId = new Map(steps.map((step) => [step.id, step]));
    const number = new Map(steps.map((step, index) => [step.id, index + 1]));
    const kids = new Map();
    const depth = new Map();
    const loose = []; // lines to a step that already has its place
    const roots = [];
    const seen = new Set();

    const tree = new Map(); // which tree a step belongs to: the main one first
    const visit = (step, at) => {
        seen.add(step.id);
        tree.set(step.id, roots.length);
        depth.set(step.id, at);
        const own = [];
        kids.set(step.id, own);
        for (const way of step.next || []) {
            const target = byId.get(way.to);
            if (!target) {
                continue;
            }
            if (seen.has(target.id)) {
                loose.push({ from: step, to: target, label: way.label || "" });
            } else {
                own.push({ step: target, label: way.label || "" });
                visit(target, at + 1);
            }
        }
    };
    const first = steps.find((step) => step.kind === "start") || steps[0];
    for (const step of first ? [first, ...steps] : []) {
        if (!seen.has(step.id)) {
            visit(step, 0);
            roots.push(step);
        }
    }

    const span = new Map();
    const measure = (step) => {
        const total = kids.get(step.id).reduce((sum, kid) => sum + measure(kid.step), 0);
        span.set(step.id, Math.max(1, total));
        return span.get(step.id);
    };
    const column = new Map(); // centre of the step, in columns
    const place = (step, from) => {
        column.set(step.id, from + span.get(step.id) / 2);
        let at = from;
        for (const kid of kids.get(step.id)) {
            place(kid.step, at);
            at += span.get(kid.step.id);
        }
    };
    let columns = 0;
    for (const root of roots) {
        measure(root);
        place(root, columns);
        columns += span.get(root.id);
    }

    // A row with answers on the lines below it gets more room.
    const rows = Math.max(0, ...depth.values()) + (steps.length ? 1 : 0);
    const labelled = new Array(rows).fill(false);
    for (const step of steps) {
        if (kids.get(step.id).some((kid) => kid.label)) {
            labelled[depth.get(step.id)] = true;
        }
    }
    const rowTop = [];
    let y = PAD;
    for (let row = 0; row < rows; row++) {
        rowTop.push(y);
        y += CARD_H + (labelled[row] ? GAP_LABELLED : GAP);
    }
    // The first column's card starts at the padding, so the picture has the same room on both sides.
    const left = (step) => PAD + column.get(step.id) * COLUMN - COLUMN / 2;
    const top = (step) => rowTop[depth.get(step.id)];

    const nodes = steps.map((step) => ({ step, number: number.get(step.id), left: left(step), top: top(step) }));
    const edges = [];
    for (const step of steps) {
        const x = left(step) + CARD_W / 2;
        const bottom = top(step) + CARD_H;
        const elbow = bottom + (labelled[depth.get(step.id)] ? GAP_LABELLED : GAP) / 2;
        for (const kid of kids.get(step.id)) {
            const kx = left(kid.step) + CARD_W / 2;
            edges.push({
                d: `M ${x} ${bottom} V ${elbow} H ${kx} V ${top(kid.step) - 5}`,
                label: kid.label,
                left: kx + 10,
                top: elbow + 8,
            });
        }
    }
    const gridWidth = PAD * 2 + Math.max(1, columns) * COLUMN - (COLUMN - CARD_W);
    // Lines that join an earlier step, or go back up, run down the right-hand side.
    loose.forEach((line, index) => {
        const lane = gridWidth + LANE * index;
        const fromY = top(line.from) + CARD_H / 2;
        const toY = top(line.to) + CARD_H / 2 + (line.from === line.to ? 0 : 12);
        edges.push({
            d: `M ${left(line.from) + CARD_W} ${fromY} H ${lane} V ${toY} H ${left(line.to) + CARD_W + 5}`,
            label: line.label,
            left: left(line.from) + CARD_W + 8,
            top: fromY - 20,
        });
    });
    const order = [...steps].sort(
        (a, b) =>
            tree.get(a.id) - tree.get(b.id) ||
            depth.get(a.id) - depth.get(b.id) ||
            column.get(a.id) - column.get(b.id)
    );
    return {
        nodes,
        edges,
        order,
        width: gridWidth + (loose.length ? LANE * loose.length + PAD : 0),
        height: (rows ? rowTop[rows - 1] + CARD_H : 0) + PAD,
    };
}

/** The picture: steps as cards on a dotted canvas, with the lines between them. */
export class SedibaFlow extends Component {
    static template = "sediba.Flow";
    static props = {
        steps: Array,
        selected: { type: [Number, Boolean], optional: true },
        onSelect: { type: Function, optional: true },
        zoom: { type: Number, optional: true },
        label: { type: String, optional: true },
    };

    setup() {
        this.kindLabel = KIND_LABEL;
    }

    get layout() {
        return layoutFlow(this.props.steps);
    }

    get zoom() {
        return this.props.zoom || 1;
    }

    /** What a screen reader hears for a step: its number, kind and words. */
    said(node) {
        return `${node.number}. ${KIND_LABEL[node.step.kind]}: ${node.step.text || _t("nothing written yet")}`;
    }

    select(step) {
        if (this.props.onSelect) {
            this.props.onSelect(step.id);
        }
    }
}

/** A diagram as it shows inside a doc: title, picture, and the same as steps. */
export class SedibaFlowBlock extends Component {
    static template = "sediba.FlowBlock";
    static components = { SedibaFlow };
    static props = {
        flow: Object,
        canEdit: { type: Boolean, optional: true },
        onEdit: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ open: false, room: 0 });
        this.kindLabel = KIND_LABEL;
        // The block is as wide as the doc's text. A picture wider than that is
        // drawn smaller so it still fits, and only scrolls once it would get too small.
        this.scroll = useRef("scroll");
        const measure = () => {
            const el = this.scroll.el;
            if (el) {
                const style = getComputedStyle(el);
                this.state.room = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
            }
        };
        const watcher = window.ResizeObserver ? new ResizeObserver(measure) : null;
        onMounted(() => {
            measure();
            if (watcher) {
                watcher.observe(this.scroll.el);
            }
        });
        onWillUnmount(() => watcher && watcher.disconnect());
    }

    get fit() {
        const width = layoutFlow(this.props.flow.steps).width;
        if (!this.state.room || !width || width <= this.state.room) {
            return 1;
        }
        return Math.max(SMALLEST, Math.floor((this.state.room / width) * 100) / 100);
    }

    get opened() {
        return this.props.flow.steps.find((step) => step.id === this.state.open);
    }

    get openedNumber() {
        return this.props.flow.steps.indexOf(this.opened) + 1;
    }

    toggle(id) {
        this.state.open = this.state.open === id ? false : id;
    }
}

/** The editor: add steps, say what comes next, and read it back as text. */
export class SedibaFlowEditor extends Component {
    static template = "sediba.FlowEditor";
    static components = { SedibaFlow };
    static props = { flow: Object, docName: { type: String, optional: true }, onDone: Function };

    setup() {
        this.orm = useService("orm");
        this.kinds = KINDS;
        const steps = JSON.parse(JSON.stringify(this.props.flow.steps || []));
        if (!steps.length) {
            steps.push({ id: 1, kind: "start", text: "", detail: "", next: [] });
        }
        this.state = useState({
            name: this.props.flow.name || "",
            steps,
            selected: steps[0].id,
            tab: "step",
            zoom: 1,
            lines: [],
        });
        this.loadTextSoon = useDebounced(() => this.loadText(), 400);
    }

    get step() {
        return this.state.steps.find((step) => step.id === this.state.selected);
    }

    get zoomLabel() {
        return `${Math.round(this.state.zoom * 100)}%`;
    }

    number(step) {
        return this.state.steps.indexOf(step) + 1;
    }

    /** The steps a step can lead to: every other one, by number and words. */
    choices(step) {
        return this.state.steps
            .filter((other) => other.id !== step.id)
            .map((other) => ({
                id: other.id,
                label: `${this.number(other)}. ${other.text || KIND_LABEL[other.kind]}`,
            }));
    }

    answerLabel(index) {
        return _t("Answer %s", index + 1);
    }

    nextLabel(way, index) {
        return way.label ? _t("Step after %s", way.label) : _t("Step after answer %s", index + 1);
    }

    blank(kind = "step") {
        const id = Math.max(0, ...this.state.steps.map((step) => step.id)) + 1;
        return { id, kind, text: "", detail: "", next: [] };
    }

    select(id) {
        this.state.selected = id;
        this.state.tab = "step";
    }

    /** A new step that nothing leads to yet. */
    addStep() {
        const step = this.blank();
        this.state.steps.push(step);
        this.select(step.id);
    }

    /** A new step right after this one: it takes over where this one led. */
    addAfter() {
        const current = this.step;
        if (!current || current.kind === "end") {
            return;
        }
        const step = this.blank();
        if (current.kind === "decision") {
            current.next.push({ label: "", to: step.id });
        } else {
            step.next = current.next.filter((way) => way.to).map((way) => ({ label: "", to: way.to }));
            current.next = [{ label: "", to: step.id }];
        }
        this.state.steps.splice(this.state.steps.indexOf(current) + 1, 0, step);
        this.select(step.id);
    }

    /** Take a step out. What led to it now leads to what came after it. */
    removeStep() {
        const current = this.step;
        if (!current) {
            return;
        }
        const onward = current.kind !== "decision" && current.next[0] ? current.next[0].to : false;
        const index = this.state.steps.indexOf(current);
        this.state.steps.splice(index, 1);
        for (const step of this.state.steps) {
            for (const way of step.next) {
                if (way.to === current.id) {
                    way.to = onward && onward !== step.id ? onward : false;
                }
            }
            if (step.kind !== "decision") {
                step.next = step.next.filter((way) => way.to);
            }
        }
        const beside = this.state.steps[Math.max(0, index - 1)];
        this.state.selected = beside ? beside.id : false;
    }

    setKind(ev) {
        const current = this.step;
        const kind = ev.target.value;
        if (kind === current.kind) {
            return;
        }
        const first = current.next[0] ? current.next[0].to : false;
        current.kind = kind;
        if (kind === "end") {
            current.next = [];
        } else if (kind === "decision") {
            current.next = [
                { label: _t("yes"), to: first },
                { label: _t("no"), to: false },
            ];
        } else {
            current.next = first ? [{ label: "", to: first }] : [];
        }
    }

    setNext(index, ev) {
        const current = this.step;
        const to = parseInt(ev.target.value, 10) || false;
        if (current.kind === "decision") {
            current.next[index].to = to;
        } else {
            current.next = to ? [{ label: "", to }] : [];
        }
    }

    addAnswer() {
        this.step.next.push({ label: "", to: false });
    }

    removeAnswer(index) {
        this.step.next.splice(index, 1);
    }

    zoomBy(by) {
        this.state.zoom = Math.min(1.5, Math.max(0.5, Math.round((this.state.zoom + by) * 10) / 10));
    }

    /** Number the steps in the order the picture reads, and show it at full size. */
    tidy() {
        const order = layoutFlow(this.state.steps).order.map((step) => step.id);
        this.state.steps.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
        this.state.zoom = 1;
        if (this.state.tab === "text") {
            this.loadText();
        }
    }

    showText() {
        this.state.tab = "text";
        return this.loadText();
    }

    flow() {
        return {
            name: this.state.name.trim() || _t("Flow diagram"),
            steps: JSON.parse(JSON.stringify(this.state.steps)),
        };
    }

    async loadText() {
        this.state.lines = await this.orm.call("sediba.workspace", "ws_flow_text", [this.flow()]);
    }

    done() {
        this.props.onDone(this.flow());
    }
}
