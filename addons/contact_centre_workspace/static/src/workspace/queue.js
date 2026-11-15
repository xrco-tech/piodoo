/** @odoo-module **/

import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { when, dialWhatsApp, dialVoip } from "./util";

const { DateTime } = luxon;
const WS = "contact.centre.workspace";
const GROUPS = ["overdue", "now", "today", "later"];

/** "40 min late", "Now", "13:30", "16 Nov 09:00". */
export function dueText(row) {
    if (row.late) {
        if (row.late < 90) {
            return _t("%s min late", row.late);
        }
        return row.late < 2880 ? _t("%s h late", Math.round(row.late / 60)) : _t("%s days late", Math.round(row.late / 1440));
    }
    if (row.group === "now") {
        return _t("Now");
    }
    return deserializeDateTime(row.due).toFormat(row.group === "today" ? "HH:mm" : "d MMM HH:mm");
}

/** "first try", "try 2 of 3". */
export function triesText(row) {
    return row.attempts ? _t("try %(n)s of %(max)s", { n: row.attempts + 1, max: row.max }) : _t("first try");
}

/** What a date-and-time box holds, as the server wants it; false when empty or unreadable. */
export function boxToServer(value) {
    const dt = value ? DateTime.fromISO(value) : null;
    return dt && dt.isValid ? serializeDateTime(dt) : false;
}

/** The My queue section: the calls this agent has to make, and the next one beside them. */
export class ContactCentreQueue extends Component {
    static template = "contact_centre_workspace.Queue";
    static props = {
        boot: Object,
        setPane: Function,
        openConversation: Function,
        onCounts: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.bus = useService("bus_service");
        this.notification = useService("notification");
        this.state = useState({
            pill: "all",
            rows: [],
            counts: { all: 0 },
            ready: false,
            overdue: 0,
            done: 0,
            pool: 0,
            agents: [],
            loading: true,
            sel: false,
            item: null,
            note: "",
            panel: null,          // later | hand | follow
            laterAt: "",
            handTo: "",
            follow: { term: "", people: [], contact: null, at: "", note: "" },
            error: "",
            busy: false,
        });
        this.dueText = dueText;
        this.when = when;
        this.refresh = useDebounced(() => this.reload(), 500);
        this.findPeople = useDebounced(() => this.searchPeople(), 300);
        this.bus.subscribe("contact_centre_queue", this.refresh);
        // Calls become due, and overdue, as time passes.
        const tick = setInterval(() => this.reload(), 60000);
        onWillDestroy(() => {
            this.bus.unsubscribe("contact_centre_queue", this.refresh);
            clearInterval(tick);
        });
        onWillStart(() => this.loadAndLand());
    }

    // ── Loading ──────────────────────────────────────────────────────────
    take(result) {
        Object.assign(this.state, {
            rows: result.rows, counts: result.counts, ready: result.ready, overdue: result.overdue,
            done: result.done, pool: result.pool, agents: result.agents,
        });
        this.props.onCounts();
    }

    async loadList() {
        this.state.loading = true;
        try {
            this.take(await this.orm.call(WS, "ws_queue", [], { pill: this.state.pill }));
        } finally {
            this.state.loading = false;
        }
    }

    async loadItem(id) {
        const item = await this.orm.call(WS, "ws_queue_item", [id]);
        if (this.state.sel === id) {
            this.state.item = item;
        }
    }

    /** Nothing open, or what was open has left the queue: show the first call. */
    async land() {
        const ids = this.state.rows.map((row) => row.id);
        if (ids.includes(this.state.sel)) {
            return;
        }
        if (ids.length) {
            await this.open(ids[0], true);
        } else {
            this.state.sel = false;
            this.state.item = null;
        }
    }

    async loadAndLand() {
        await this.loadList();
        await this.land();
    }

    /** The queue changed somewhere, or time passed. Not while something is being typed. */
    async reload() {
        if (this.state.busy || this.state.panel || this.state.note) {
            return;
        }
        await this.loadList();
        if (this.state.rows.some((row) => row.id === this.state.sel)) {
            await this.loadItem(this.state.sel);
        } else {
            await this.land();
        }
    }

    async open(id, stay = false) {
        this.state.sel = id;
        this.state.note = "";
        this.state.panel = null;
        this.state.error = "";
        if (!stay) {
            this.props.setPane("thread");
        }
        await this.loadItem(id);
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        const counts = this.state.counts;
        return [
            { key: "all", label: _t("All"), count: counts.all },
            { key: "callback", label: _t("Callbacks"), count: counts.callback },
            { key: "campaign", label: _t("Campaigns"), count: counts.campaign },
            { key: "missed", label: _t("Missed calls"), count: counts.missed },
            { key: "follow", label: _t("Follow-ups"), count: counts.follow },
        ];
    }

    setPill(key) {
        this.state.pill = key;
        this.loadAndLand();
    }

    get groups() {
        const names = { overdue: _t("Overdue"), now: _t("Due now"), today: _t("Later today"), later: _t("Later") };
        return GROUPS
            .map((key) => ({ key, name: names[key], rows: this.state.rows.filter((row) => row.group === key) }))
            .filter((group) => group.rows.length);
    }

    /** "WhatsApp or phone · try 2 of 3". */
    howText(row) {
        if (row.auto) {
            return _t("Phone · rings for you");
        }
        const how = row.wa ? _t("WhatsApp or phone") : _t("Phone only");
        return `${how} · ${triesText(row)}`;
    }

    get summary() {
        const todo = this.state.counts.all;
        const calls = todo === 1 ? _t("1 call to make") : _t("%s calls to make", todo);
        return this.state.overdue ? _t("%(calls)s · %(late)s overdue", { calls, late: this.state.overdue }) : calls;
    }

    get progress() {
        const total = this.state.done + this.state.counts.all;
        return { total, percent: total ? Math.round((100 * this.state.done) / total) : 0 };
    }

    async toggleReady() {
        this.take(await this.orm.call(WS, "ws_queue_ready", [!this.state.ready]));
        await this.land();
    }

    async takeNext() {
        const id = await this.orm.call(WS, "ws_queue_take", []);
        this.state.pill = "all";
        await this.loadList();
        await this.open(id);
    }

    // ── The call ─────────────────────────────────────────────────────────
    callWhatsApp() {
        const item = this.state.item;
        dialWhatsApp(this.env.services, { phone: item.phone, name: item.name, partnerId: item.partner_id, bot: item.script || undefined });
    }

    callVoip() {
        dialVoip(this.env.services, this.state.item.phone);
    }

    full(value) {
        return value ? deserializeDateTime(value).toFormat("d MMM, HH:mm") : "";
    }

    get facts() {
        const item = this.state.item;
        const facts = [];
        if (item.assigned_by) {
            const same = item.mine && item.assigned_by === this.props.boot.me.name;
            facts.push({ label: _t("Assigned by"), value: `${same ? _t("You") : item.assigned_by}, ${this.full(item.assigned_at)}` });
        } else if (item.assigned_at) {
            facts.push({ label: _t("Assigned"), value: _t("Shared out automatically, %s", this.full(item.assigned_at)) });
        }
        let tries = item.attempts ? _t("%(n)s of %(max)s made", { n: item.attempts, max: item.max }) : _t("None yet, %s allowed", item.max);
        if (item.last_attempt) {
            tries += _t(" · last one %s", this.full(item.last_attempt));
        }
        facts.push({ label: _t("Tries"), value: tries });
        facts.push({
            label: _t("How to call"),
            value: item.auto ? _t("The dialler rings them by phone when you are ready")
                : this.props.boot.voip ? _t("Your choice: WhatsApp call or phone") : _t("WhatsApp call (you have no phone extension)"),
        });
        if (item.permission) {
            facts.push({ label: _t("WhatsApp calls"), value: item.permission, ok: item.wa });
        }
        return facts;
    }

    /** The call after this one, for the strip at the bottom. */
    get next() {
        const rows = this.state.rows;
        const at = rows.findIndex((row) => row.id === this.state.sel);
        return rows.length > 1 ? rows[(at + 1) % rows.length] : null;
    }

    skip() {
        this.open(this.next.id);
    }

    // ── After the call ───────────────────────────────────────────────────
    showPanel(panel) {
        this.state.error = "";
        this.state.panel = this.state.panel === panel ? null : panel;
        if (panel === "later" && !this.state.laterAt) {
            this.state.laterAt = DateTime.local().plus({ hours: 1 }).startOf("hour").toFormat("yyyy-MM-dd'T'HH:mm");
        }
    }

    async outcome(outcome, extra = {}) {
        const id = this.state.sel;
        if (!id || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.orm.call(WS, "ws_queue_outcome", [id, outcome], { note: this.state.note, ...extra });
        } finally {
            this.state.busy = false;
        }
        this.state.note = "";
        this.state.panel = null;
        // Still on the queue (a retry, a later time): the next call opens instead.
        const next = this.next;
        await this.loadList();
        if (next && this.state.rows.some((row) => row.id === next.id)) {
            await this.open(next.id, true);
        } else {
            this.state.sel = false;
            await this.land();
        }
    }

    saveLater() {
        const at = boxToServer(this.state.laterAt);
        if (!at) {
            this.state.error = _t("Pick a date and time.");
            return;
        }
        this.outcome("later", { when: at });
    }

    saveHand() {
        this.outcome("hand", { user_id: parseInt(this.state.handTo, 10) || false });
    }

    get others() {
        return this.state.agents.filter((agent) => agent.name !== this.props.boot.me.name);
    }

    // ── A follow-up of my own ────────────────────────────────────────────
    openFollow() {
        this.state.follow = {
            term: "", people: [], contact: null, note: "",
            at: DateTime.local().plus({ days: 1 }).set({ hour: 9, minute: 0 }).toFormat("yyyy-MM-dd'T'HH:mm"),
        };
        this.state.error = "";
        this.state.panel = this.state.panel === "follow" ? null : "follow";
    }

    onFollowTerm(ev) {
        this.state.follow.term = ev.target.value;
        this.state.follow.contact = null;
        this.findPeople();
    }

    async searchPeople() {
        this.state.follow.people = await this.orm.call(WS, "ws_queue_people", [this.state.follow.term]);
    }

    pickPerson(person) {
        this.state.follow.contact = person;
        this.state.follow.term = person.name;
        this.state.follow.people = [];
    }

    async saveFollow() {
        const follow = this.state.follow;
        const at = boxToServer(follow.at);
        if (!follow.contact || !at) {
            this.state.error = _t("Pick a person, a date and a time.");
            return;
        }
        const id = await this.orm.call(WS, "ws_queue_follow_up", [follow.contact.id, at], { note: follow.note });
        this.state.panel = null;
        this.state.pill = "all";
        await this.loadList();
        await this.open(id, true);
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    openConversation() {
        this.props.openConversation(this.state.item.contact_id);
    }
}
