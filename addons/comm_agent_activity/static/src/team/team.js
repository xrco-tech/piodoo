/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { describeTarget } from "./strip";

const REPORT = "comm.agent.activity.report";
const BAR_HEIGHT = 110; // px
const MANY_REVERSED = 3;

/** 1484 -> "1 484". */
function num(n) {
    return String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** Seconds as "24 h 05", or "12 min" under an hour. */
function hm(seconds) {
    const minutes = Math.round((seconds || 0) / 60);
    if (minutes < 60) {
        return _t("%s min", minutes);
    }
    return _t("%(h)s h %(m)s", { h: Math.floor(minutes / 60), m: String(minutes % 60).padStart(2, "0") });
}

/** A wait or a time taken: "45 s", "5 min", "3 h". */
function span(seconds) {
    if (!seconds) {
        return "–";
    }
    if (seconds < 90) {
        return _t("%s s", Math.round(seconds));
    }
    if (seconds < 2 * 3600) {
        return _t("%s min", Math.round(seconds / 60));
    }
    return _t("%s h", Math.round(seconds / 3600));
}

/** The Team report: every agent for a supervisor, their own figures for an agent. */
export class TeamReport extends Component {
    static template = "comm_agent_activity.Team";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.num = num;
        this.hm = hm;
        this.span = span;
        this.state = useState({
            boot: null,
            source: "both",
            period: "week",
            view: "team", // team | agent | points | targets
            agentId: false,
            team: null,
            agent: null,
            points: null,
            edits: {},
            targets: null,
            targetEdits: {},
            person: null,
            busy: false,
        });
        onWillStart(async () => {
            const params = (this.props.action && this.props.action.params) || {};
            const boot = await this.orm.call(REPORT, "boot", [params.source || "both"]);
            this.state.boot = boot;
            this.state.source = boot.source;
            this.state.view = boot.supervisor ? "team" : "agent";
            await this.load();
        });
    }

    get periods() {
        return [
            { key: "today", label: _t("Today") },
            { key: "week", label: _t("This week") },
            { key: "last_week", label: _t("Last week") },
            { key: "month", label: _t("This month") },
        ];
    }

    get sources() {
        const sources = this.state.boot.sources;
        return sources.length > 1 ? [...sources, { key: "both", label: _t("Both") }] : [];
    }

    async load() {
        const { view, source, period, agentId } = this.state;
        this.state.busy = true;
        try {
            if (view === "team") {
                this.state.team = await this.orm.call(REPORT, "team", [source, period]);
            } else if (view === "agent") {
                this.state.agent = await this.orm.call(REPORT, "agent", [agentId, source, period]);
            } else if (view === "targets") {
                this.setTargets(await this.orm.call(REPORT, "targets", [source]));
            } else {
                this.state.points = await this.orm.call(REPORT, "points", []);
                this.state.edits = Object.fromEntries(this.state.points.rows.map((row) => [row.action, String(row.points)]));
            }
        } finally {
            this.state.busy = false;
        }
    }

    setPeriod(period) {
        this.state.period = period;
        return this.load();
    }

    setSource(source) {
        this.state.source = source;
        return this.load();
    }

    openAgent(userId) {
        this.state.view = "agent";
        this.state.agentId = userId;
        this.state.agent = null;
        return this.load();
    }

    openTeam() {
        this.state.view = "team";
        return this.load();
    }

    openPoints() {
        this.state.view = "points";
        this.state.points = null;
        return this.load();
    }

    // ── The team ────────────────────────────────────────────────────────

    get tiles() {
        const t = this.state.team.tiles;
        const idle = t.agents - t.active;
        const change =
            t.change === false
                ? _t("Nothing earlier to compare with")
                : t.change >= 0
                  ? _t("%s% more than the period before", t.change)
                  : _t("%s% fewer than the period before", -t.change);
        return [
            {
                key: "agents",
                label: _t("Agents active"),
                value: _t("%(n)s of %(of)s", { n: t.active, of: t.agents }),
                note: idle > 0 ? _t("%s did nothing in this period", idle) : _t("Everyone did something"),
            },
            { key: "actions", label: _t("Actions"), value: num(t.actions), note: change },
            {
                key: "time",
                label: _t("Active time"),
                value: hm(t.active_seconds),
                note: t.active ? _t("About %s per active agent", hm(t.active_seconds / t.active)) : "",
            },
            {
                key: "wait",
                label: _t("Reply wait, median"),
                value: span(t.wait_median),
                note: _t("Target is %s", span(t.target_seconds)),
                bad: t.wait_median > t.target_seconds,
            },
            {
                key: "reversed",
                label: _t("Decisions reversed later"),
                value: num(t.reversed),
                note: t.reversed_top > 1 ? _t("%s belong to one agent", t.reversed_top) : t.reversed ? "" : _t("None"),
                bad: t.reversed_top >= MANY_REVERSED,
            },
        ];
    }

    get gridStyle() {
        const n = this.state.team.columns.length + 5;
        return `grid-template-columns: minmax(190px, 2.6fr) repeat(${n}, minmax(74px, 1fr)); min-width: ${190 + n * 84}px`;
    }

    flag(row) {
        if (row.fast_flag) {
            return { warn: true, text: _t("%s jobs checked in under a minute, no notes", row.fast) };
        }
        if (!row.actions) {
            return { text: _t("No activity") };
        }
        return { text: row.days === 1 ? _t("Active on 1 day") : _t("Active on %s days", row.days) };
    }

    calls(row) {
        return row.calls ? `${num(row.calls)}, ${hm(row.talk_seconds)}` : "0";
    }

    manyReversed(row) {
        return row.reversed >= MANY_REVERSED;
    }

    get backlog() {
        return this.state.team.backlog.map((item) => {
            const eta = !item.waiting
                ? _t("Nothing waiting")
                : item.weeks === 1
                  ? _t("About 1 week at this pace")
                  : item.weeks
                    ? _t("About %s weeks at this pace", item.weeks)
                    : _t("Not catching up at this pace");
            const share = item.waiting + item.done ? Math.round((100 * item.done) / (item.waiting + item.done)) : 0;
            return {
                key: item.key,
                title: `${num(item.waiting)} ${item.label}`,
                eta,
                behind: Boolean(item.waiting) && !item.weeks,
                bar: `width: ${share}%`,
                detail: _t("In the last 7 days the team did %(done)s, about %(each)s each, and %(arrived)s new ones arrived.", {
                    done: num(item.done),
                    each: span(item.each_seconds),
                    arrived: num(item.new),
                }),
            };
        });
    }

    get hours() {
        const { hours, tiles } = this.state.team;
        const top = Math.max(...hours.map((h) => h.median), 1);
        return hours.map((h) => ({
            key: h.hour,
            label: `${String(h.hour).padStart(2, "0")}:00`,
            wait: h.n ? span(h.median) : "",
            tone: h.median > tiles.target_seconds ? "bad" : h.median > 0.7 * tiles.target_seconds ? "warn" : "",
            bar: `height: ${h.n ? Math.max(4, Math.round((BAR_HEIGHT * h.median) / top)) : 0}px`,
        }));
    }

    get hasWaits() {
        return this.state.team.hours.some((h) => h.n);
    }

    download() {
        const team = this.state.team;
        const head = [
            _t("Agent"),
            _t("Active time (minutes)"),
            ...team.columns.map((col) => col.label),
            _t("Reply wait (seconds)"),
            _t("Calls"),
            _t("Talk time (minutes)"),
            _t("Reversed later"),
            _t("Score"),
        ];
        const lines = team.rows.map((row) => [
            row.name,
            Math.round(row.active_seconds / 60),
            ...team.columns.map((col) => row.counts[col.key] || 0),
            row.wait_median || "",
            row.calls,
            Math.round(row.talk_seconds / 60),
            row.reversed,
            row.score,
        ]);
        const cell = (value) => `"${String(value).replace(/"/g, '""')}"`;
        const csv = [head, ...lines].map((line) => line.map(cell).join(",")).join("\r\n");
        const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `team-${team.source}-${team.period}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    // ── One agent ───────────────────────────────────────────────────────

    get scoreNote() {
        const a = this.state.agent;
        const diff = a.me.score - a.score_before;
        if (!a.score_before && !a.me.score) {
            return "";
        }
        if (!diff) {
            return _t("Same as the period before");
        }
        return diff > 0 ? _t("Up %s on the period before", num(diff)) : _t("Down %s on the period before", num(-diff));
    }

    /** Lower is better for waits and reversals; more is neither good nor bad. */
    tone(mine, team, lowerIsBetter) {
        if (!lowerIsBetter || mine === false || team === false || mine === team) {
            return "";
        }
        return mine < team ? "ok" : "bad";
    }

    get compare() {
        const { me, team, columns } = this.state.agent;
        const rows = [{ key: "time", label: _t("Active time"), me: hm(me.active_seconds), team: hm(team.active_seconds) }];
        for (const col of columns) {
            rows.push({ key: col.key, label: col.label, me: num(me.counts[col.key]), team: num(team.counts[col.key]) });
        }
        rows.push(
            { key: "calls", label: _t("Calls"), me: this.calls(me), team: num(team.calls) },
            {
                key: "wait",
                label: _t("Reply wait"),
                me: span(me.wait_median),
                team: span(team.wait_median),
                tone: this.tone(me.wait_median, team.wait_median, true),
            },
            {
                key: "reversed",
                label: _t("Reversed later"),
                me: num(me.reversed),
                team: num(team.reversed),
                tone: this.tone(me.reversed, team.reversed, true),
            }
        );
        if (columns.some((col) => col.key === "job_check")) {
            rows.push(
                { key: "each", label: _t("Time per job check"), me: span(me.check_median), team: span(team.check_median) },
                {
                    key: "noted",
                    label: _t("Job checks with a note"),
                    me: me.noted === false ? "–" : `${me.noted}%`,
                    team: team.noted === false ? "–" : `${team.noted}%`,
                }
            );
        }
        return rows;
    }

    get concerns() {
        const { me, team } = this.state.agent;
        const lines = [];
        if (me.fast_flag) {
            lines.push(
                _t("%(fast)s of %(checks)s jobs were checked in under a minute each, with no note.", {
                    fast: me.fast,
                    checks: me.checks,
                })
            );
        }
        if (me.reversed >= MANY_REVERSED) {
            lines.push(
                _t("Other agents later changed %(n)s of their decisions. The team average is %(team)s.", {
                    n: me.reversed,
                    team: num(team.reversed),
                })
            );
        }
        return lines;
    }

    get days() {
        const days = this.state.agent.days;
        const top = Math.max(...days.map((d) => d.seconds), 1);
        return days.map((d, index) => ({
            key: index,
            label: d.label,
            time: d.seconds ? hm(d.seconds) : "",
            bar: `height: ${d.seconds ? Math.max(4, Math.round((BAR_HEIGHT * d.seconds) / top)) : 0}px`,
        }));
    }

    get log() {
        return this.state.agent.log.map((line) => {
            const parts = [];
            if (line.result) {
                parts.push(line.result);
            }
            if (line.wait_seconds) {
                parts.push(_t("waited %s", span(line.wait_seconds)));
            }
            if (line.fast) {
                parts.push(_t("%s, no note", span(line.seconds)));
            } else if (line.no_note) {
                parts.push(_t("no note"));
            }
            if (line.reversed_by) {
                parts.push(_t("reversed by %s", line.reversed_by));
            }
            return {
                id: line.id,
                when: deserializeDateTime(line.at).toFormat("ccc d LLL, HH:mm"),
                action: line.action,
                name: line.name,
                result: parts.join(" · "),
                tone: line.reversed_by || line.fast ? "bad" : "",
            };
        });
    }

    // ── Targets ─────────────────────────────────────────────────────────

    describe(item) {
        return describeTarget(item);
    }

    get teamTargets() {
        const targets = this.state.team.targets;
        return targets.rows.map((row) => ({
            ...row,
            cells: row.cells.map((cell, index) => ({
                key: targets.columns[index].key,
                ...(cell ? describeTarget(cell) : { text: "–", tone: "none", bar: "width: 0" }),
            })),
            pill: row.reached === row.of ? "ok" : row.reached * 2 < row.of ? "low" : "",
        }));
    }

    get targetGrid() {
        const n = this.state.team.targets.columns.length;
        return `grid-template-columns: minmax(190px, 1.6fr) repeat(${n}, minmax(110px, 1fr)) 96px; min-width: ${290 + n * 120}px`;
    }

    get progress() {
        const p = this.state.agent.progress;
        const withWords = (item) => ({ key: item.metric, label: item.label, ...describeTarget(item) });
        const todo = p.today.filter((item) => !item.reached).map((item) => item.label.toLowerCase());
        return {
            has: p.today.length + p.week.length > 0,
            head: p.of ? _t("%(n)s of %(of)s targets reached today", { n: p.reached, of: p.of }) : _t("This week's targets"),
            hint: !p.of ? "" : todo.length ? _t("Still to reach: %s", todo.join(", ")) : _t("Everything for today is reached"),
            today: p.today.map(withWords),
            week: p.week.map(withWords),
            history: p.history.map((day, index) => ({ key: index, ...day, full: day.of && day.reached === day.of })),
        };
    }

    openTargets() {
        this.state.view = "targets";
        this.state.targets = null;
        this.state.person = null;
        return this.load();
    }

    setTargets(data) {
        this.state.targets = data;
        this.state.targetEdits = Object.fromEntries(
            data.rows.map((row) => [row.metric, { on: row.on, value: String(row.value) }])
        );
        this.state.person = null;
    }

    /** "At least this many", "each working day", and what the team does now, for one row. */
    targetWords(row) {
        const many = row.unit === "minutes" ? _t("No longer than this, in minutes")
            : row.unit === "percent" ? _t("At least this share, in percent")
            : row.unit === "points" ? _t("At least this many points")
            : row.kind === "max" ? _t("No more than this many") : _t("At least this many");
        const per = row.unit === "minutes" ? _t("median over the day")
            : row.unit === "percent" ? _t("over the day")
            : row.period === "week" ? _t("each week") : _t("each working day");
        let now = _t("Nothing to go on yet");
        if (row.now !== false) {
            now = row.unit === "minutes" ? _t("Median %s min", row.now)
                : row.unit === "percent" ? _t("Average %s%", row.now)
                : row.period === "week" ? _t("Average %s a week", num(row.now)) : _t("Average %s a day", num(row.now));
        }
        return { many, per, now };
    }

    /** "Jobs checked 12 · Score 300" for an agent with their own targets. */
    personWords(person) {
        const labels = Object.fromEntries(this.state.targets.rows.map((row) => [row.metric, row.label]));
        return Object.entries(person.values).map(([metric, value]) => `${labels[metric] || metric} ${value}`).join(" · ");
    }

    get freeAgents() {
        const taken = new Set(this.state.targets.people.map((person) => person.user_id));
        return this.state.targets.agents.filter((agent) => !taken.has(agent.id));
    }

    editPerson(person) {
        const values = Object.fromEntries(this.state.targets.rows.map((row) => [row.metric, ""]));
        if (person) {
            for (const [metric, value] of Object.entries(person.values)) {
                values[metric] = String(value);
            }
        }
        this.state.person = {
            isNew: !person,
            user_id: person ? person.user_id : this.freeAgents[0]?.id || false,
            name: person ? person.name : "",
            note: person ? person.note : "",
            values,
        };
    }

    async saveTargets() {
        await this.busy(async () => {
            this.setTargets(await this.orm.call(REPORT, "targets_save", [{ ...this.state.targetEdits }]));
            this.notification.add(_t("Targets saved. Agents see them straight away."), { type: "success" });
        });
    }

    async savePerson() {
        const { user_id, note, values } = this.state.person;
        await this.busy(async () => {
            this.setTargets(await this.orm.call(REPORT, "target_person_save", [user_id, note, { ...values }]));
        });
    }

    async removePerson() {
        const userId = this.state.person.user_id;
        await this.busy(async () => {
            this.setTargets(await this.orm.call(REPORT, "target_person_remove", [userId]));
        });
    }

    async busy(work) {
        this.state.busy = true;
        try {
            await work();
        } finally {
            this.state.busy = false;
        }
    }

    // ── The points ──────────────────────────────────────────────────────

    setPoints(action, ev) {
        this.state.edits[action] = ev.target.value;
    }

    async savePoints() {
        this.state.busy = true;
        try {
            this.state.points = await this.orm.call(REPORT, "points_save", [{ ...this.state.edits }]);
            this.notification.add(_t("Points saved. Scores now use them, for past periods too."), { type: "success" });
            await this.openTeam();
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("comm_agent_activity.team", TeamReport);
