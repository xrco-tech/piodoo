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

/** A round figure for one third of the chart's height: 1, 2, 2.5, 5 times a power of ten, or a round time. */
function niceStep(raw, seconds) {
    if (seconds) {
        const steps = [300, 600, 900, 1800, 3600, 7200, 10800, 14400, 21600, 28800, 43200, 86400];
        return steps.find((step) => step >= raw) || Math.ceil(raw / 86400) * 86400;
    }
    if (raw <= 1) {
        return 1;
    }
    const pow = 10 ** Math.floor(Math.log10(raw));
    const part = raw / pow;
    return (part <= 1 ? 1 : part <= 2 ? 2 : part <= 2.5 && pow >= 10 ? 2.5 : part <= 5 ? 5 : 10) * pow;
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
            picked: [], // user ids; none means every agent
            pickOpen: false,
            pickDraft: {},
            measure: "actions", // actions | score | seconds
            hover: null,
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
                this.state.hover = null;
                this.state.team = await this.orm.call(REPORT, "team", [source, period, this.state.picked]);
                this.state.picked = this.state.team.picked;
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

    // ── Which agents ────────────────────────────────────────────────────

    get agentsLabel() {
        const picked = this.state.picked;
        if (!picked.length) {
            return _t("All agents");
        }
        if (picked.length === 1) {
            const agent = this.state.team.agents.find((one) => one.id === picked[0]);
            return agent ? agent.name : _t("1 agent");
        }
        return _t("%s agents", picked.length);
    }

    get pickCount() {
        return this.state.team.agents.filter((agent) => this.state.pickDraft[agent.id]).length;
    }

    get allPicked() {
        return this.pickCount === this.state.team.agents.length;
    }

    get pickNote() {
        const count = this.pickCount;
        if (!count) {
            return _t("Tick at least one agent");
        }
        return this.allPicked ? _t("Everyone") : _t("%(n)s of %(all)s", { n: count, all: this.state.team.agents.length });
    }

    togglePick() {
        if (this.state.pickOpen) {
            return this.closePick();
        }
        const picked = this.state.picked;
        this.state.pickDraft = Object.fromEntries(
            this.state.team.agents.map((agent) => [agent.id, !picked.length || picked.includes(agent.id)])
        );
        this.state.pickOpen = true;
    }

    closePick() {
        this.state.pickOpen = false;
    }

    pickAll() {
        const on = !this.allPicked;
        this.state.pickDraft = Object.fromEntries(this.state.team.agents.map((agent) => [agent.id, on]));
    }

    pickOne(id) {
        this.state.pickDraft[id] = !this.state.pickDraft[id];
    }

    applyPick() {
        const ids = this.state.team.agents.filter((agent) => this.state.pickDraft[agent.id]).map((agent) => agent.id);
        this.state.picked = ids.length === this.state.team.agents.length ? [] : ids;
        this.state.pickOpen = false;
        return this.load();
    }

    // ── Activity per day ────────────────────────────────────────────────

    get measures() {
        return [
            { key: "actions", label: _t("Actions") },
            { key: "score", label: _t("Score") },
            { key: "seconds", label: _t("Active time") },
        ];
    }

    setMeasure(measure) {
        this.state.measure = measure;
        this.state.hover = null;
    }

    setHover(index) {
        this.state.hover = index;
    }

    /** One point's figure for what is being counted. A day of reversals can score below nothing: drawn as none. */
    chartValue(figures) {
        return Math.max(0, (figures && figures[this.state.measure]) || 0);
    }

    get chartFormat() {
        return this.state.measure === "seconds" ? hm : num;
    }

    get chart() {
        const { chart, period } = this.state.team;
        const measure = this.state.measure;
        const points = chart.points;
        const format = this.chartFormat;
        const values = points.map((point) => this.chartValue(point));
        const before = points.map((point) => (point.before ? this.chartValue(point.before) : null));
        const top = Math.max(0, ...values, ...before.map((value) => value || 0));
        const step = niceStep(top / 3, measure === "seconds");
        const max = step * 3;
        const share = (value) => `height:${((100 * value) / max).toFixed(2)}%`;
        const kinds = chart.kinds
            .map((kind, index) => ({ ...kind, cls: `k${index + 1}` }))
            .filter((kind) => points.some((point) => point.counts[kind.key]));
        const peak = values.indexOf(Math.max(...values));
        const bars = points.map((point, index) => {
            const value = values[index];
            let segs = [];
            if (measure === "actions") {
                segs = kinds
                    .filter((kind) => point.counts[kind.key])
                    .map((kind) => ({ key: kind.key, cls: kind.cls, style: share(point.counts[kind.key]) }));
            } else if (value) {
                segs = [{ key: "all", cls: "k1", style: share(value) }];
            }
            if (segs.length) {
                segs[segs.length - 1].cls += " top";
            }
            return {
                key: point.key,
                label: point.label,
                weekend: point.weekend,
                now: point.now,
                segs,
                top: value && (index === peak || point.now) ? format(value) : "",
                aria: `${point.long}: ${format(value)}`,
            };
        });
        const line = before.some((value) => value)
            ? before
                  .map((value, index) =>
                      value === null ? "" : `${(((index + 0.5) * 100) / points.length).toFixed(2)},${(100 - (100 * value) / max).toFixed(2)}`
                  )
                  .filter(Boolean)
                  .join(" ")
            : "";
        const hourly = chart.unit === "hour";
        const subs = {
            actions: hourly ? _t("Everything done each hour, by kind of work") : _t("Everything done each day, by kind of work"),
            score: hourly ? _t("Points earned each hour") : _t("Points earned each day"),
            seconds: hourly ? _t("Time worked each hour") : _t("Time worked each day"),
        };
        const beforeLabel =
            period === "today" ? _t("Yesterday") : period === "month" ? _t("Four weeks before") : _t("The week before");
        return {
            title: hourly ? _t("Activity per hour") : _t("Activity per day"),
            sub: subs[measure],
            empty: !top,
            legend: measure === "actions" ? kinds : [],
            ticks: [3, 2, 1, 0].map((n) => format(step * n)),
            bars,
            line,
            beforeLabel,
            width: `min-width:${points.length * 22}px`,
            note: hourly
                ? _t("Point at a bar for the hour's figures.")
                : _t("Point at a bar for the day's figures. Saturdays and Sundays have grey labels."),
        };
    }

    /** The figures of the bar under the pointer, as a small card beside it. */
    get hover() {
        const index = this.state.hover;
        const { chart } = this.state.team;
        const point = index === null ? null : chart.points[index];
        if (!point) {
            return null;
        }
        const format = this.chartFormat;
        const measure = this.state.measure;
        const rows =
            measure === "actions"
                ? chart.kinds
                      .filter((kind) => point.counts[kind.key])
                      .map((kind) => ({ key: kind.key, label: kind.label, n: point.counts[kind.key] }))
                      .sort((a, b) => b.n - a.n)
                      .map((row) => ({ ...row, value: num(row.n) }))
                : [];
        const at = ((index + 0.5) * 100) / chart.points.length;
        return {
            title: point.long,
            rows,
            total: format(this.chartValue(point)),
            before: point.before ? format(this.chartValue(point.before)) : "",
            style: at > 50 ? `right:${(100 - at + 3).toFixed(1)}%` : `left:${(at + 3).toFixed(1)}%`,
        };
    }

    // ── The team ────────────────────────────────────────────────────────

    /** How many targets this view is measured against, in words for the settings line. */
    get targetsNote() {
        const on = this.state.team.targets.columns.length;
        if (!on) {
            return _t("No targets are on for this view.");
        }
        return on === 1 ? _t("1 target is on for this view.") : _t("%s targets are on for this view.", on);
    }

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
