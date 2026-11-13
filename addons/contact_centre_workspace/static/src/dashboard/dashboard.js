/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const { DateTime } = luxon;
const WS = "contact.centre.workspace";
const CHART_HEIGHT = 140; // px

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

/** The Contact Centre dashboard: what needs someone now, then how the period went. */
export class ContactCentreDashboardPage extends Component {
    static template = "contact_centre_workspace.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ period: "today", data: null, cards: [], loading: true });
        onWillStart(() => Promise.all([this.load(), this.loadCards()]));
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(WS, "ws_dashboard", [this.state.period]);
        } finally {
            this.state.loading = false;
        }
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

    // ── Needs you now ────────────────────────────────────────────────────
    since(value) {
        return duration(DateTime.local().diff(deserializeDateTime(value)).as("seconds"));
    }

    get todo() {
        const { todo, messages } = this.state.data;
        const failed = messages.failed_by.map((f) => `${f.n} ${f.channel}`).join(", ");
        const tiles = [
            {
                key: "unread", n: todo.unread, label: _t("Unread conversations"), hot: todo.unread > 0,
                sub: todo.waiting_since ? _t("Longest has waited %s", this.since(todo.waiting_since)) : _t("Nobody is waiting"),
            },
            {
                key: "missed", n: todo.missed_today, label: _t("Missed calls today"), hot: todo.missed_today > 0,
                sub: todo.missed_today ? _t("Call them back from Calls") : _t("None missed"),
            },
            {
                key: "no_outcome", n: todo.no_outcome, label: _t("Calls with no outcome"),
                sub: _t("Answered WhatsApp calls in the last 30 days waiting for a wrap-up"),
            },
            {
                key: "failed", n: messages.failed, label: _t("Messages that did not send"),
                sub: messages.failed ? failed : _t("Everything went out %s", this.periodWords),
            },
        ];
        if (todo.held !== false) {
            tiles.push({
                key: "held", n: todo.held, label: _t("Sidekick needs your yes"),
                sub: todo.held ? _t("A change is waiting for your go-ahead") : _t("Nothing is waiting"),
            });
        }
        return tiles;
    }

    openWorkspace(params) {
        this.action.doAction({ type: "ir.actions.client", tag: "contact_centre_workspace", name: _t("Workspace"), params });
    }

    openTodo(key) {
        const data = this.state.data;
        if (key === "failed") {
            this.action.doAction({
                type: "ir.actions.act_window", name: _t("Messages that did not send"), res_model: "contact.centre.message",
                views: [[false, "list"], [false, "form"]], domain: [["status", "=", "failed"]],
            });
        } else if (!data.is_agent) {
            return; // the workspace is for agents
        } else if (key === "unread") {
            this.openWorkspace({ section: "inbox", pill: "unread" });
        } else if (key === "missed") {
            this.openWorkspace({ section: "calls", pill: "missed" });
        } else if (key === "no_outcome") {
            this.openWorkspace({ section: "calls", pill: "no_outcome" });
        } else if (key === "held") {
            this.openWorkspace({ section: "ai" });
        }
    }

    // ── Messages ─────────────────────────────────────────────────────────
    /** One stack of bars per day, scaled to the busiest day. */
    get days() {
        const days = this.state.data.messages.days;
        const top = Math.max(1, ...days.map((d) => d.whatsapp + d.sms + d.email));
        const px = (n) => `${Math.round((CHART_HEIGHT * n) / top)}px`;
        return days.map((d) => ({
            key: d.date, whatsapp: px(d.whatsapp), sms: px(d.sms), email: px(d.email),
            title: `${DateTime.fromISO(d.date).toFormat("d MMM")}: ${d.whatsapp + d.sms + d.email}`,
        }));
    }

    get chartAlt() {
        const days = this.state.data.messages.days;
        const top = Math.max(0, ...days.map((d) => d.whatsapp + d.sms + d.email));
        return _t("Messages per day for the last 14 days, by channel. The busiest day had %s.", top);
    }

    get chartEnds() {
        const days = this.state.data.messages.days;
        const label = (d) => DateTime.fromISO(d.date).toFormat("d MMM");
        return [label(days[0]), label(days[Math.floor(days.length / 2)]), _t("Today")];
    }

    // ── Calls ────────────────────────────────────────────────────────────
    clock(seconds) {
        const minutes = Math.floor(seconds / 60);
        return `${minutes}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
    }

    get callTiles() {
        const calls = this.state.data.calls;
        return [
            { n: calls.answered, label: _t("Answered"), cls: "ok" },
            { n: calls.missed, label: _t("Missed"), cls: calls.missed ? "bad" : "" },
            { n: calls.outgoing, label: _t("Outgoing"), cls: "" },
            { n: calls.average_seconds ? this.clock(calls.average_seconds) : "—", label: _t("Average call"), cls: "" },
        ];
    }

    get callSummary() {
        const calls = this.state.data.calls;
        const count = calls.total === 1 ? _t("1 call") : _t("%s calls", calls.total);
        return calls.talk_seconds ? _t("%(count)s · %(time)s talking", { count, time: duration(calls.talk_seconds) }) : count;
    }

    /** Each line's bar is as long as its share of the busier line. */
    get lines() {
        const lines = this.state.data.calls.lines;
        const top = Math.max(1, ...lines.map((l) => l.total));
        return lines.map((l) => ({
            ...l,
            name: l.line === "whatsapp" ? "WhatsApp" : "VoIP",
            other: l.total - l.answered - l.missed - l.outgoing,
            rest: top - l.total,
            note: l.total === 1 ? _t("1 call") : _t("%s calls", l.total),
            alt: _t("%(answered)s answered, %(missed)s missed, %(outgoing)s outgoing", l),
        }));
    }

    // ── Smaller cards ────────────────────────────────────────────────────
    get conversationTotal() {
        const c = this.state.data.conversations;
        return c.open + c.pending + c.resolved;
    }

    get replyTime() {
        const replies = this.state.data.replies;
        return replies.median_seconds === false ? "—" : duration(replies.median_seconds);
    }

    get outcomes() {
        const outcomes = this.state.data.outcomes;
        const top = Math.max(1, ...outcomes.map((o) => o.n));
        return outcomes.map((o, index) => ({ ...o, width: `${Math.max(4, Math.round((100 * o.n) / top))}%`, first: index === 0 }));
    }

    // ── Campaigns ────────────────────────────────────────────────────────
    get campaigns() {
        return this.state.data.campaigns.rows.map((c) => {
            let note;
            let width = "0%";
            if (c.state === "draft") {
                note = c.total === 1 ? _t("1 contact · not started") : _t("%s contacts · not started", c.total);
            } else if (c.outbound) {
                note = _t("%(done)s of %(total)s sent", c) + (c.failed ? " · " + _t("%s failed", c.failed) : "");
                width = `${Math.round((100 * c.done) / Math.max(1, c.total))}%`;
            } else {
                note = c.messages === 1 ? _t("Inbound · 1 message") : _t("Inbound · %s messages", c.messages);
                width = "100%";
            }
            return { ...c, note, width };
        });
    }

    openCampaign(id) {
        if (this.state.data.is_agent) {
            this.openWorkspace({ section: "campaigns", open_id: id });
        }
    }

    // ── Busiest hours ────────────────────────────────────────────────────
    /** Five shades, darkest for the busiest hour. */
    get hours() {
        const hours = this.state.data.hours;
        const top = Math.max(1, ...hours.map((h) => h.n));
        return hours.map((h) => ({ ...h, shade: h.n ? Math.min(4, Math.ceil((4 * h.n) / top)) : 0 }));
    }

    get hourNote() {
        const hours = this.state.data.hours;
        const busiest = hours.reduce((best, h) => (h.n > best.n ? h : best), hours[0]);
        if (!busiest.n) {
            return _t("Nothing came in over the last 7 days.");
        }
        const pad = (hour) => `${String(hour).padStart(2, "0")}:00`;
        return _t("Most people get in touch between %(from)s and %(to)s.", { from: pad(busiest.hour), to: pad(busiest.hour + 1) });
    }

    // ── Your own cards (set up by a manager or by Sidekick) ──────────────
    async loadCards() {
        try {
            const cards = await this.orm.searchRead(
                "contact.centre.dashboard.card", [["active", "=", true]],
                ["name", "model_name", "metric_type", "domain", "group_by_field"], { order: "sequence asc" }
            );
            this.state.cards = await Promise.all(cards.map((card) => this.loadCard(card)));
        } catch {
            this.state.cards = []; // no cards, or none this user may read
        }
    }

    /** A card that cannot be worked out shows a dash; it never breaks the page. */
    async loadCard(card) {
        let value = null;
        let breakdown = [];
        try {
            const domain = card.domain || [];
            if (card.metric_type === "group_by" && card.group_by_field) {
                const groups = await this.orm.readGroup(card.model_name, domain, [card.group_by_field], [card.group_by_field]);
                breakdown = groups.map((g) => {
                    const label = g[card.group_by_field];
                    return { label: Array.isArray(label) ? label[1] : label || _t("(none)"), n: g[`${card.group_by_field}_count`] };
                });
                value = breakdown.reduce((sum, b) => sum + b.n, 0);
            } else {
                value = await this.orm.searchCount(card.model_name, domain);
            }
        } catch {
            value = null;
        }
        return { ...card, value, breakdown };
    }

    openCard(card) {
        this.action.doAction({
            type: "ir.actions.act_window", name: card.name, res_model: card.model_name,
            views: [[false, "list"], [false, "form"]], domain: card.domain || [],
        });
    }
}

// The Dashboard menu's action keeps its name: this page takes its place.
registry.category("actions").add("contact_centre_dashboard", ContactCentreDashboardPage, { force: true });
