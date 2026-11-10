/** @odoo-module **/

import { Component, onWillStart, onWillDestroy, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const WS = "chat2work.workspace";
const AVATAR_COLOURS = ["#b5651d", "#2f6f8f", "#a3466b", "#7a4fa3", "#2e7d5b", "#8a5a44", "#5a6fb0", "#3f7f6a", "#8f2d3a", "#6b6f7a"];
const COUNTS_EVERY_MS = 60000;
// Channels an agent types on; everything else shows as an event on the thread.
const CHAT_CHANNELS = ["whatsapp", "sms", "email"];
const VERIFY_ACTIONS = {
    unverified: "action_mark_unverified",
    verified: "action_mark_verified",
    invalid: "action_mark_invalid",
    cancelled: "action_mark_cancelled",
};

const VIEWS = {
    inbox: {
        search: true,
        label: _t("Conversations"),
        what: _t("candidates"),
        pills: [["all", _t("All")], ["reply", _t("Needs reply")], ["callbacks", _t("Callbacks")],
                ["whatsapp", _t("WhatsApp")], ["sms", _t("SMS only")]],
        list: (pill, search, offset, limit) => ["ws_inbox", [pill, search, offset, limit]],
        paged: true,
        detail: "ws_candidate",
    },
    cand: {
        search: true,
        label: _t("Candidates"),
        what: _t("candidates"),
        pills: [],
        list: () => ["ws_pipeline", []],
        detail: false,
    },
    jobs: {
        search: true,
        label: _t("Job listings"),
        what: _t("listings"),
        pills: [["all", _t("Open")], ["to_verify", _t("To verify")], ["to_review", _t("To review")],
                ["ready", _t("Ready to share")], ["closed", _t("Closed")]],
        list: (pill, search, offset, limit) => ["ws_listings", [pill, search, offset, limit]],
        paged: true,
        detail: "ws_listing",
    },
    book: {
        search: false,
        label: _t("Bookings"),
        what: _t("slots"),
        pills: [["upcoming", _t("Upcoming")], ["past", _t("Past")]],
        list: (pill, search, offset, limit) => ["ws_slots", [pill, offset, limit]],
        paged: true,
        detail: "ws_slot",
    },
    idc: {
        search: false,
        label: _t("ID checks"),
        what: _t("checks"),
        pills: [["all", _t("All")], ["verified", _t("Verified")], ["not_valid", _t("Not valid")],
                ["failed", _t("Failed")]],
        list: (pill, search, offset, limit) => ["ws_checks", [pill, offset, limit]],
        paged: true,
        detail: "ws_check",
    },
};

const RAIL = [
    { id: "inbox", icon: "fa-comments-o", label: _t("Inbox"), view: "inbox", pill: "all", count: "inbox" },
    { id: "callbacks", icon: "fa-phone", label: _t("Callbacks"), view: "inbox", pill: "callbacks", count: "callbacks" },
    { id: "cand", icon: "fa-users", label: _t("Candidates"), view: "cand" },
    { id: "jobs", icon: "fa-briefcase", label: _t("Jobs"), view: "jobs", pill: "all", count: "jobs" },
    { id: "book", icon: "fa-calendar", label: _t("Bookings"), view: "book", pill: "upcoming" },
    { id: "idc", icon: "fa-id-card-o", label: _t("ID checks"), view: "idc", pill: "all", count: "idc", idCheck: true },
];

const FOLLOW_UPS = [
    ["all", _t("All in this stage")],
    ["mine", _t("My follow-ups")],
    ["overdue", _t("Overdue follow-ups")],
    ["none", _t("No follow-up planned")],
    ["callback", _t("Callback requested")],
];

export class Chat2workWorkspace extends Component {
    static template = "chat2work_workspace.Workspace";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.views = VIEWS;
        this.followUps = FOLLOW_UPS;

        this.state = useState({
            boot: null,
            counts: {},
            view: "inbox",
            pills: { inbox: "all", jobs: "all", book: "upcoming", idc: "all" },
            search: "",
            rows: [],
            loadingList: true,
            selId: false,
            detail: false,
            loadingDetail: false,
            pane: "list",
            composer: "",
            sending: false,
            show: "all", // follow-up filter on the Candidates screen
            pinnedId: false,
            cvHelp: false, // { url, name } while the candidate's CV page is open
            smsFor: false, // the candidate an agent chose to SMS although they use WhatsApp
            more: false, // the list has rows beyond the ones loaded
            loadingMore: false,
        });

        this.threadRef = useRef("thread");
        useEffect(
            () => {
                const el = this.threadRef.el;
                if (el && this.state.view === "inbox") {
                    el.scrollTop = el.scrollHeight;
                }
            },
            () => [this.state.detail]
        );

        this.debouncedLoad = useDebounced(() => this.loadList(), 300);

        onWillStart(async () => {
            this.state.boot = await this.orm.call(WS, "ws_bootstrap", []);
            this.state.counts = this.state.boot.counts;
            await this.loadList();
        });

        const timer = setInterval(() => this.loadCounts(), COUNTS_EVERY_MS);
        onWillDestroy(() => clearInterval(timer));
    }

    // ── Derived ─────────────────────────────────────────────────────────

    get rail() {
        return RAIL.filter((r) => !r.idCheck || this.state.boot.can_id_check);
    }

    get activeRail() {
        const { view, pills } = this.state;
        return view === "inbox" && pills.inbox === "callbacks" ? "callbacks" : view;
    }

    get view() {
        return VIEWS[this.state.view];
    }

    get pill() {
        return this.state.pills[this.state.view];
    }

    /** The thread, with a divider wherever the day changes. */
    get timeline() {
        const items = [];
        let lastDay = "";
        const entries = this.state.detail.timeline || [];
        // Only the latest USSD session starts open, so older ones don't flood the thread.
        const latestSession = entries.findLast((e) => e.session)?.id;
        for (const entry of entries) {
            const day = this.day(entry.at);
            if (day !== lastDay) {
                items.push({ key: "d" + entry.id, kind: "day", label: day });
                lastDay = day;
            }
            if (entry.session) {
                items.push({ ...entry, ...this.sessionView(entry.session), key: "m" + entry.id,
                             kind: "session", open: entry.id === latestSession });
                continue;
            }
            const chat = CHAT_CHANNELS.includes(entry.channel);
            items.push({
                ...entry,
                key: "m" + entry.id,
                kind: entry.channel === "ussd" ? "ussd" : chat ? (entry.dir === "inbound" ? "in" : "out") : "event",
                failed: entry.status === "failed",
            });
        }
        return items;
    }

    /**
     * A USSD session as turns to draw. It finished when the last thing shown
     * was a closing message (no options); otherwise the caller left part-way.
     */
    sessionView(turns) {
        const last = turns[turns.length - 1];
        const finished = Boolean(last) && last.dir === "out" && !last.options.length;
        return {
            turns: turns.map((turn, index) => ({ ...turn, key: index, end: finished && index === turns.length - 1 })),
            finished,
            tag: finished ? last.prompt.split(/[.!]/)[0] : _t("Not finished"),
            length: this.sessionLength(turns),
        };
    }

    /** How long a USSD session took, first screen to last, or "" when the times weren't kept. */
    sessionLength(turns) {
        const first = turns[0]?.at;
        const last = turns[turns.length - 1]?.at;
        if (!first || !last) {
            return "";
        }
        const seconds = Math.max(0, Math.round(deserializeDateTime(last).diff(deserializeDateTime(first), "seconds").seconds));
        const minutes = Math.floor(seconds / 60);
        return minutes ? _t("%(minutes)s min %(seconds)s s", { minutes, seconds: seconds % 60 }) : _t("%s s", seconds);
    }

    /** Why the reply box is locked, or false when a typed message can go. */
    get composerLock() {
        const c = this.state.detail;
        if (!c.phone) {
            return _t("This candidate has no phone number.");
        }
        if (this.channel === "whatsapp" && !c.window_open) {
            return _t("WhatsApp only allows a template now: their last message was more than 24 hours ago.");
        }
        return false;
    }

    /** How the next message goes: WhatsApp if they use it, unless the agent picked SMS. */
    get channel() {
        const c = this.state.detail;
        return c.whatsapp && this.state.smsFor !== c.id ? "whatsapp" : "sms";
    }

    setChannel(channel) {
        this.state.smsFor = channel === "sms" ? this.state.detail.id : false;
    }

    openTemplates() {
        return this.candidateAction("action_c2w_open_message", this.state.detail.id, false,
                                    { default_channel: this.channel });
    }

    get composerPlaceholder() {
        const c = this.state.detail;
        const first = (c.name || "").split(" ")[0];
        if (this.channel === "whatsapp") {
            return _t("Message %s on WhatsApp…", first);
        }
        return c.whatsapp ? _t("Message %s by SMS…", first) : _t("Message %s by SMS (no WhatsApp)…", first);
    }

    // ── Formatting ──────────────────────────────────────────────────────

    initials(name) {
        const words = (name || "?").trim().split(/\s+/);
        return ((words[0][0] || "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
    }

    colour(name) {
        let hash = 0;
        for (const ch of name || "") {
            hash = (hash * 31 + ch.charCodeAt(0)) % 9973;
        }
        return AVATAR_COLOURS[hash % AVATAR_COLOURS.length];
    }

    when(value) {
        if (!value) {
            return "";
        }
        const dt = deserializeDateTime(value);
        const today = luxon.DateTime.local();
        if (dt.hasSame(today, "day")) {
            return dt.toFormat("HH:mm");
        }
        return dt.toFormat(dt.hasSame(today, "year") ? "d MMM" : "d MMM yyyy");
    }

    time(value) {
        return value ? deserializeDateTime(value).toFormat("HH:mm") : "";
    }

    day(value) {
        const dt = deserializeDateTime(value);
        return dt.hasSame(luxon.DateTime.local(), "day") ? _t("Today") : dt.toFormat("d MMM yyyy");
    }

    slotWhen(value) {
        return value ? deserializeDateTime(value).toFormat("ccc d MMM, HH:mm") : "";
    }

    closing(row) {
        if (!row.closing_on) {
            return "";
        }
        const days = row.closing_in_days;
        if (days < 0) {
            return _t("Past closing");
        }
        return days === 0 ? _t("Closes today") : days === 1 ? _t("Closes tomorrow") : _t("%s days", days);
    }

    channelBadge(code) {
        return { whatsapp: "WA", sms: "SMS", ussd: "*#", web: "CV", email: "@", voice: "☎", voip: "☎" }[code] || "";
    }

    tagClass(state) {
        if (["verified", "approved", "completed", "ready", "placed", "put_forward", "cv_ready"].includes(state)) {
            return "ok";
        }
        if (["help", "to_verify", "to_review", "not_valid", "failed", "no_show", "invalid", "new"].includes(state)) {
            return "warn";
        }
        return "plain";
    }

    // ── Loading ─────────────────────────────────────────────────────────

    async loadCounts() {
        this.state.counts = await this.orm.silent.call(WS, "ws_counts", []);
    }

    /** Load the list. `keep` reloads as many rows as are already showing, so a
     *  refresh after an action doesn't drop the pages the agent loaded. */
    async loadList({ keep = false } = {}) {
        const view = this.state.view;
        const page = this.state.boot.page_size;
        const limit = keep ? Math.max(page, this.state.rows.length) : page;
        const [method, args] = this.view.list(this.pill, this.state.search, 0, limit);
        this.state.loadingList = true;
        try {
            const rows = await this.orm.call(WS, method, args);
            if (view !== this.state.view) {
                return; // the agent moved on while this was loading
            }
            this.state.rows = rows;
            this.state.more = Boolean(this.view.paged) && rows.length >= limit;
        } finally {
            this.state.loadingList = false;
        }
        const ids = this.state.rows.map((r) => r.id);
        // A candidate opened from another screen stays open even when the list
        // (the most recent 100) doesn't include them.
        const pinned = this.state.pinnedId && this.state.selId === this.state.pinnedId;
        if (!ids.includes(this.state.selId) && !pinned) {
            this.state.selId = ids.length ? ids[0] : false;
        }
        await this.loadDetail();
    }

    async loadDetail() {
        const id = this.state.selId;
        if (!id) {
            this.state.detail = false;
            return;
        }
        this.state.loadingDetail = true;
        try {
            let detail;
            if (this.state.view === "cand") {
                const stage = this.state.rows.find((r) => r.id === id);
                detail = { ...stage, ...(await this.orm.call(WS, "ws_stage", [id, this.state.show, this.state.search])) };
            } else {
                detail = await this.orm.call(WS, this.view.detail, [id]);
            }
            if (id === this.state.selId) {
                this.state.detail = detail;
            }
        } finally {
            this.state.loadingDetail = false;
        }
    }

    async loadMore() {
        if (this.state.loadingMore) {
            return;
        }
        const view = this.state.view;
        const page = this.state.boot.page_size;
        const [method, args] = this.view.list(this.pill, this.state.search, this.state.rows.length, page);
        this.state.loadingMore = true;
        try {
            const rows = await this.orm.call(WS, method, args);
            if (view === this.state.view) {
                const have = new Set(this.state.rows.map((r) => r.id));
                this.state.rows.push(...rows.filter((r) => !have.has(r.id)));
                this.state.more = rows.length >= page;
            }
        } finally {
            this.state.loadingMore = false;
        }
    }

    badge(count) {
        return count > 99 ? "99+" : count;
    }

    async refresh() {
        await Promise.all([this.loadList({ keep: true }), this.loadCounts()]);
    }

    // ── Navigation ──────────────────────────────────────────────────────

    async go(view, pill) {
        this.state.view = view;
        if (pill) {
            this.state.pills[view] = pill;
        }
        this.state.search = "";
        this.state.pane = "list";
        this.state.selId = false;
        this.state.pinnedId = false;
        this.state.detail = false;
        this.state.rows = [];
        await this.loadList();
    }

    onRail(item) {
        return this.go(item.view, item.pill);
    }

    async setPill(pill) {
        this.state.pills[this.state.view] = pill;
        this.state.pinnedId = false;
        this.state.pane = "list";
        await this.loadList();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.debouncedLoad();
    }

    async select(id) {
        this.state.selId = id;
        this.state.pinnedId = false;
        this.state.pane = "thread";
        this.state.composer = "";
        await this.loadDetail();
    }

    setPane(pane) {
        this.state.pane = pane;
    }

    async openCandidate(candidateId) {
        if (!candidateId) {
            return;
        }
        this.state.view = "inbox";
        this.state.pills.inbox = "all";
        this.state.search = "";
        this.state.selId = candidateId;
        this.state.pinnedId = candidateId;
        this.state.pane = "thread";
        this.state.detail = false;
        this.state.rows = [];
        await this.loadList();
    }

    openRecord(model, id) {
        return this.action.doAction(
            { type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]], target: "current" }
        );
    }

    // ── Candidate actions ───────────────────────────────────────────────

    /** Run one of the candidate form's buttons and show whatever it opens. */
    async candidateAction(method, candidateId = this.state.detail.id, done = false, context = {}) {
        const result = await this.orm.call("chat2work.candidate", method, [[candidateId]], { context });
        if (result && typeof result === "object" && result.type) {
            if (result.type === "ir.actions.act_window" && !result.views) {
                // A form button gets this filled in by the server; a direct call doesn't.
                result.views = (result.view_mode || "form").split(",").map((mode) => [false, mode]);
            }
            if (result.params && result.params.next) {
                delete result.params.next; // the form reloads itself; here we reload below
            }
            await this.action.doAction(result, { onClose: () => this.refresh() });
        } else if (done) {
            this.notification.add(done, { type: "success" });
        }
        await this.refresh();
    }

    async setStage(stage) {
        if (stage === this.state.detail.stage) {
            return;
        }
        await this.orm.write("chat2work.candidate", [this.state.detail.id], { stage });
        await this.refresh();
    }

    async setCallbackState(state) {
        const callback = this.state.detail.callback;
        if (!callback || callback.state === state) {
            return;
        }
        await this.orm.write("chat2work.callback.request", [callback.id], { state });
        await this.refresh();
    }

    async saveCallbackNotes(ev) {
        const callback = this.state.detail.callback;
        const notes = ev.target.value;
        if (callback && notes !== callback.notes) {
            await this.orm.write("chat2work.callback.request", [callback.id], { notes });
            callback.notes = notes;
        }
    }

    async helpBuildCv() {
        this.state.cvHelp = await this.orm.call(WS, "ws_cv_help", [this.state.detail.id]);
    }

    async closeCvHelp() {
        this.state.cvHelp = false;
        await this.refresh(); // the CV state and stage may have changed
    }

    onComposerInput(ev) {
        this.state.composer = ev.target.value;
    }

    onComposerKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const text = this.state.composer.trim();
        if (!text || this.state.sending || this.composerLock) {
            return;
        }
        this.state.sending = true;
        try {
            this.state.detail = await this.orm.call(WS, "ws_send", [this.state.detail.id, text, this.channel]);
            this.state.composer = "";
        } finally {
            this.state.sending = false;
        }
        this.loadList({ keep: true });
    }

    // ── Candidates screen ───────────────────────────────────────────────

    async setShow(show) {
        this.state.show = show;
        await this.loadDetail();
    }

    // ── Job listing actions ─────────────────────────────────────────────

    async setVerification(state) {
        if (state === this.state.detail.verification_state) {
            return;
        }
        await this.orm.call("chat2work.listing", VERIFY_ACTIONS[state], [[this.state.detail.id]]);
        await this.refresh();
    }

    async suggestCandidates() {
        await this.orm.call("chat2work.listing", "action_suggest_candidates", [[this.state.detail.id]]);
        await this.refresh();
    }

    async setMatch(match, approve) {
        await this.orm.call("chat2work.listing.match", approve ? "action_approve" : "action_reject", [[match.id]]);
        await this.refresh();
    }

    // ── Booking actions ─────────────────────────────────────────────────

    async setBooking(booking, state) {
        await this.orm.write("chat2work.interview.booking", [booking.id], { state });
        await this.refresh();
    }

    // ── ID check actions ────────────────────────────────────────────────

    async updateIdNumber() {
        await this.action.doAction("chat2work.action_chat2work_id_update", {
            additionalContext: { default_candidate_id: this.state.detail.candidate_id },
            onClose: () => this.refresh(),
        });
    }

    async refreshBalance() {
        await this.orm.call("chat2work.verify.account", "action_refresh_balance", [[this.state.detail.account.id]]);
        await this.loadDetail();
    }
}

registry.category("actions").add("chat2work_workspace", Chat2workWorkspace);
