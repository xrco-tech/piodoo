/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const REPORT = "comm.agent.activity.report";
const EVERY_MS = 60 * 1000;

function num(n) {
    return String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/**
 * One target as words: the value ("14 of 20"), a line on where it stands, a
 * short mark for the strip, and a tone (ok | low | todo) for the colour.
 */
export function describeTarget(item) {
    const { unit, kind, value, target, reached } = item;
    const none = value === null || value === undefined;
    let text, note, mark;
    if (unit === "minutes") {
        text = none ? "–" : _t("%s min", value);
        note = none ? _t("No replies yet") : reached ? _t("Within the %s minutes", target) : _t("Over the %s minutes", target);
        mark = none ? "" : reached ? _t("On target") : _t("Over %s min", target);
    } else if (unit === "percent") {
        text = none ? "–" : `${value}%`;
        if (none) {
            note = _t("No job checks yet");
            mark = "";
        } else if (reached) {
            note = mark = _t("Reached");
        } else {
            note = _t("Below the %s% asked for.", target);
            if (item.missing) {
                note += " " + _t("%(missing)s of %(checks)s have no note.", { missing: item.missing, checks: item.checks });
            }
            mark = _t("Below %s%", target);
        }
    } else if (kind === "max") {
        text = _t("%(n)s of %(max)s allowed", { n: num(value), max: num(target) });
        note = mark = reached ? _t("Within the limit") : _t("Over the limit");
    } else {
        text = _t("%(n)s of %(of)s", { n: num(value), of: num(target) });
        const left = num(target - value);
        if (reached) {
            note = mark = _t("Reached");
        } else if (item.metric === "score" && item.days_done) {
            note = item.on_pace
                ? _t("%(left)s to go, on pace after %(days)s of 5 working days", { left, days: item.days_done })
                : _t("%(left)s to go, behind pace after %(days)s of 5 working days", { left, days: item.days_done });
            mark = _t("%s to go", left);
        } else {
            note = mark = _t("%s to go", left);
        }
    }
    // Nothing measured yet is neither good nor bad.
    const tone = none ? "todo" : reached || item.on_pace ? "ok" : unit === "percent" || kind === "max" ? "low" : "todo";
    return { text, note, mark, tone, bar: `width: ${item.pct}%` };
}

/** A slim line at the top of a workspace: the agent's progress on today's targets. */
export class AgentTargetStrip extends Component {
    static template = "comm_agent_activity.Strip";
    static props = { source: String, action: String };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.root = useRef("root");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
        const timer = setInterval(() => this.load(), EVERY_MS);
        onWillDestroy(() => clearInterval(timer));
        // The workspace makes room for the line only while there is one.
        useEffect(
            (el, shown) => {
                const host = el && el.parentElement;
                if (host) {
                    host.classList.toggle("o_caa_has_strip", shown);
                }
                return () => host && host.classList.remove("o_caa_has_strip");
            },
            () => [this.root.el, this.shown]
        );
    }

    async load() {
        try {
            this.state.data = await this.orm.silent.call(REPORT, "progress", [this.props.source]);
        } catch {
            this.state.data = null; // the line is a convenience: never in the way of the work
        }
    }

    get shown() {
        return Boolean(this.state.data && this.state.data.today.length);
    }

    get all() {
        const data = this.state.data;
        return this.shown && data.reached === data.of;
    }

    get lead() {
        const { reached, of } = this.state.data;
        if (this.all) {
            return of === 1 ? _t("Today's target is reached") : _t("All %s targets reached today", of);
        }
        return _t("Today: %(n)s of %(of)s reached", { n: reached, of });
    }

    get items() {
        return this.state.data.today.map((item) => ({ key: item.metric, label: item.label, ...describeTarget(item) }));
    }

    open() {
        return this.actionService.doAction(this.props.action);
    }
}
