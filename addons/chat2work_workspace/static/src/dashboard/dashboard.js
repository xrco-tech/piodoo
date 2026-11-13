/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const { DateTime } = luxon;
const WS = "chat2work.workspace";
const CHART_HEIGHT = 140; // px
const STAGE_COLOUR = { help: "bad", placed: "ok", not_available: "grey" };

/** "42 min", "1 h 12 min", "2 days". */
function duration(seconds) {
    const minutes = Math.max(1, Math.round(seconds / 60));
    if (minutes < 60) {
        return _t("%s min", minutes);
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 48) {
        return minutes % 60 ? _t("%(h)s h %(m)s min", { h: hours, m: minutes % 60 }) : _t("%s h", hours);
    }
    return _t("%s days", Math.round(hours / 24));
}

/** The Chat2Work dashboard: what needs an agent now, then how things stand. */
export class Chat2workDashboard extends Component {
    static template = "chat2work_workspace.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.alerts = useService("chat2work_alerts");
        this.state = useState({ period: "today", data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call(WS, "ws_dashboard", [this.state.period]);
    }

    setPeriod(period) {
        if (period !== this.state.period) {
            this.state.period = period;
            this.load();
        }
    }

    get periods() {
        return [
            { key: "today", label: _t("Today") },
            { key: "7d", label: _t("7 days") },
            { key: "30d", label: _t("30 days") },
        ];
    }

    get periodWords() {
        return { today: _t("today"), "7d": _t("in the last 7 days"), "30d": _t("in the last 30 days") }[this.state.period];
    }

    get today() {
        return DateTime.local().toFormat("cccc d MMMM");
    }

    since(value) {
        return duration(DateTime.local().diff(deserializeDateTime(value)).as("seconds"));
    }

    /** Show a list or a record in the Workspace. */
    open(target) {
        this.alerts.open(target);
    }

    // ── Needs you now ────────────────────────────────────────────────────
    get todo() {
        const todo = this.state.data.todo;
        const jobs = todo.jobs_verify + todo.jobs_review;
        const tiles = [
            {
                key: "reply", n: todo.reply, label: _t("Waiting for a reply"), hot: todo.reply > 0, target: { pill: "reply" },
                sub: todo.reply_since ? _t("Oldest has waited %s", this.since(todo.reply_since)) : _t("Nobody is waiting"),
            },
            {
                key: "callbacks", n: todo.callbacks, label: _t("Callbacks to make"), hot: todo.callbacks_new > 0,
                target: { pill: "callbacks" },
                sub: todo.callback_since ? _t("Oldest asked %s ago", this.since(todo.callback_since)) : _t("None asked for"),
            },
            {
                key: "jobs", n: jobs, label: _t("Jobs to check"),
                target: { view: "jobs", pill: todo.jobs_verify ? "to_verify" : "to_review" },
                sub: jobs ? _t("%(verify)s to verify, %(review)s to review", { verify: todo.jobs_verify, review: todo.jobs_review })
                    : _t("All checked"),
            },
        ];
        if (todo.id_open !== false) {
            tiles.push({
                key: "ids", n: todo.id_open, label: _t("ID checks open"), target: { view: "cand", pill: "idc", sub: "open" },
                sub: todo.id_open ? _t("%s not confirmed by Home Affairs", todo.id_failed) : _t("None open"),
            });
        }
        tiles.push({
            key: "unknown", n: todo.unknown, label: _t("Not candidates"), hot: todo.unknown > 0, target: { pill: "unknown" },
            sub: _t("Numbers that wrote in without signing up"),
        });
        return tiles;
    }

    // ── Candidates by stage ──────────────────────────────────────────────
    get stages() {
        const stages = this.state.data.stages;
        const top = Math.max(1, ...stages.map((s) => s.total));
        return stages.map((s) => ({
            ...s, cls: STAGE_COLOUR[s.id] || "navy", width: s.total ? `${Math.max(3, Math.round((100 * s.total) / top))}%` : "0%",
        }));
    }

    get stageNote() {
        const stages = this.state.data.stages;
        const callbacks = stages.reduce((sum, s) => sum + s.callbacks, 0);
        const overdue = stages.reduce((sum, s) => sum + s.overdue, 0);
        const parts = [];
        if (callbacks) {
            parts.push(callbacks === 1 ? _t("1 has asked for a callback") : _t("%s have asked for a callback", callbacks));
        }
        if (overdue) {
            parts.push(overdue === 1 ? _t("1 has an overdue follow-up") : _t("%s have an overdue follow-up", overdue));
        }
        return parts.join(" · ");
    }

    openStage(stage) {
        this.open({ view: "cand", pill: "stages", sel: stage.id });
    }

    // ── New candidates ───────────────────────────────────────────────────
    get days() {
        const days = this.state.data.new.days;
        const top = Math.max(1, ...days.map((d) => d.whatsapp + d.ussd + d.other));
        const px = (n) => `${Math.round((CHART_HEIGHT * n) / top)}px`;
        return days.map((d) => ({
            key: d.date, whatsapp: px(d.whatsapp), ussd: px(d.ussd), other: px(d.other),
            title: `${DateTime.fromISO(d.date).toFormat("d MMM")}: ${d.whatsapp + d.ussd + d.other}`,
        }));
    }

    get chartAlt() {
        const days = this.state.data.new.days;
        const top = Math.max(0, ...days.map((d) => d.whatsapp + d.ussd + d.other));
        return _t("New candidates per day for the last 14 days, by how they signed up. The busiest day had %s.", top);
    }

    get chartEnds() {
        const days = this.state.data.new.days;
        const label = (d) => DateTime.fromISO(d.date).toFormat("d MMM");
        return [label(days[0]), label(days[Math.floor(days.length / 2)]), _t("Today")];
    }

    get hasOther() {
        return this.state.data.new.days.some((d) => d.other);
    }

    /** "62% on WhatsApp, 38% on USSD" over the 14 days. */
    get split() {
        const days = this.state.data.new.days;
        const whatsapp = days.reduce((sum, d) => sum + d.whatsapp, 0);
        const all = days.reduce((sum, d) => sum + d.whatsapp + d.ussd + d.other, 0);
        const ussd = days.reduce((sum, d) => sum + d.ussd, 0);
        if (!all) {
            return _t("Nobody signed up in the last 14 days");
        }
        // Rounded so the two add up when nobody signed up another way.
        const share = Math.round((100 * whatsapp) / all);
        const rest = whatsapp + ussd === all ? 100 - share : Math.round((100 * ussd) / all);
        return _t("%(wa)s on WhatsApp, %(ussd)s on USSD in 14 days", { wa: `${share}%`, ussd: `${rest}%` });
    }

    // ── Smaller cards ────────────────────────────────────────────────────
    get cvTotal() {
        const cvs = this.state.data.cvs;
        return cvs.done + cvs.started + cvs.help + cvs.none;
    }

    get replyTime() {
        const replies = this.state.data.replies;
        return replies.median_seconds === false ? "—" : duration(replies.median_seconds);
    }

    get idTiles() {
        const ids = this.state.data.ids;
        return [
            { n: ids.failed, label: _t("Not confirmed"), cls: ids.failed ? "bad" : "" },
            { n: ids.waiting, label: _t("Did not finish"), cls: "" },
            { n: ids.not_done, label: _t("Not done yet"), cls: "" },
            { n: ids.verified, label: _t("Verified"), cls: "ok" },
        ];
    }

    get credits() {
        const credits = this.state.data.ids.credits;
        return credits === false ? "" : _t("%s credits left", Math.round(credits * 100) / 100);
    }

    // ── Jobs and bookings ────────────────────────────────────────────────
    jobTag(job) {
        return ["to_verify", "to_review"].includes(job.work_state) ? "warn" : "ok";
    }

    openJob(job) {
        this.open({ view: "jobs", pill: "all", sel: job.id });
    }

    bookingWhen(value) {
        const at = deserializeDateTime(value);
        const now = DateTime.local();
        if (at.hasSame(now, "day")) {
            return _t("Today %s", at.toFormat("HH:mm"));
        }
        return at.toFormat(at.diff(now).as("days") < 6 ? "ccc HH:mm" : "d MMM HH:mm");
    }

    openBooking(booking) {
        this.open(booking.candidate_id ? { candidate_id: booking.candidate_id } : { view: "book", pill: "upcoming" });
    }

    askSidekick() {
        this.open({ view: "side" });
    }
}

registry.category("actions").add("chat2work_dashboard", Chat2workDashboard);
