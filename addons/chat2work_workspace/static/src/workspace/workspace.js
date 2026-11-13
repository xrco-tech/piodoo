/** @odoo-module **/

import { Component, onWillStart, onWillDestroy, useEffect, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const WS = "chat2work.workspace";
const LIVE_CHANNEL = "chat2work_workspace";
const LIVE_TYPE = "chat2work_workspace/changed";
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
        pills: [["all", _t("All")], ["reply", _t("Needs reply")], ["help", _t("Needs help")], ["callbacks", _t("Callbacks")],
                ["whatsapp", _t("WhatsApp")], ["sms", _t("SMS only")], ["unknown", _t("Not candidates")]],
        list: (pill, search, offset, limit) =>
            pill === "unknown" ? ["ws_unknown", [search, offset, limit]] : ["ws_inbox", [pill, search, offset, limit]],
        paged: true,
        detail: "ws_candidate",
    },
    cand: {
        search: true,
        label: _t("Candidates"),
        what: _t("candidates"),
        pills: [["stages", _t("Stages")], ["no_cv", _t("No CV")], ["cv_started", _t("CV started")],
                ["jobs_ready", _t("Jobs to send")], ["idc", _t("ID check")]],
        list: (pill, search, offset, limit, sub) =>
            pill === "stages" ? ["ws_pipeline", []] : ["ws_candidates", [pill, sub, search, offset, limit]],
        paged: true,
        detail: "ws_candidate",
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
    side: {
        search: true,
        label: _t("Sidekick"),
        what: _t("chats"),
        pills: [["all", _t("All")], ["cand", _t("About a candidate")]],
        list: (pill, search, offset, limit) => ["ws_sidekick_chats", [pill, search, offset, limit]],
        paged: true,
        detail: "ws_sidekick_chat",
    },
};

// The ID check filter on Candidates: [sub-filter, label, its count in counts.lists].
const ID_SUBS = [
    ["open", _t("Open"), "id_open"],
    ["failed", _t("Failed"), "id_failed"],
    ["waiting", _t("Waiting"), "id_waiting"],
    ["not_done", _t("Not done"), "id_not_done"],
];

const RAIL = [
    { id: "inbox", icon: "fa-comments-o", label: _t("Inbox"), view: "inbox", pill: "all", count: "inbox" },
    { id: "callbacks", icon: "fa-phone", label: _t("Callbacks"), view: "inbox", pill: "callbacks", count: "callbacks" },
    { id: "cand", icon: "fa-users", label: _t("Candidates"), view: "cand" },
    { id: "jobs", icon: "fa-briefcase", label: _t("Jobs"), view: "jobs", pill: "all", count: "jobs" },
    { id: "book", icon: "fa-calendar", label: _t("Bookings"), view: "book", pill: "upcoming" },
    { id: "side", spark: true, label: _t("Sidekick"), view: "side" },
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
        this.bus = useService("bus_service");
        this.alerts = useService("chat2work_alerts");
        this.rail = RAIL;
        this.followUps = FOLLOW_UPS;

        this.state = useState({
            boot: null,
            counts: {},
            view: "inbox",
            pills: { inbox: "all", cand: "stages", jobs: "all", book: "upcoming", side: "all" },
            idSub: "open", // the ID check sub-filter on the Candidates screen
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
            // The assistant: what is running, and its answers for one candidate at a time.
            ai: { busy: "", forId: false, summary: "", chat: [], question: "" },
            more: false, // the list has rows beyond the ones loaded
            loadingMore: false,
            // The sidekick: what a new chat offers, the question being typed and the one being answered.
            side: { start: null, question: "", pending: "", busy: false, error: "" },
        });

        this.threadRef = useRef("thread");
        useEffect(
            () => {
                const el = this.threadRef.el;
                if (el && (["candidate", "unknown"].includes(this.kind) || this.state.view === "side")) {
                    el.scrollTop = el.scrollHeight;
                }
            },
            () => [this.state.detail, this.state.side.pending, this.state.side.error]
        );

        // The reply box grows with its text (a drafted reply is several lines), up to its CSS max-height.
        this.composerRef = useRef("composer");
        useEffect(
            () => {
                const el = this.composerRef.el;
                if (el) {
                    el.style.height = "auto";
                    el.style.height = el.scrollHeight + "px";
                }
            },
            () => [this.state.composer, this.composerRef.el]
        );

        this.debouncedLoad = useDebounced(() => this.loadList(), 300);

        onWillStart(async () => {
            this.state.boot = await this.orm.call(WS, "ws_bootstrap", []);
            this.state.counts = this.state.boot.counts;
            // An alert that opened the Workspace says what to show.
            const target = this.alerts.takePending();
            if (target && target.view === "side") {
                await this.openSidekick();
                return;
            }
            if (target) {
                this.applyTarget(target);
            }
            await this.loadList();
        });

        // While this screen is up, alerts open their candidate here instead of reloading it.
        const show = (target) => this.openTarget(target);
        this.alerts.attach(show);
        onWillDestroy(() => this.alerts.detach(show));

        const timer = setInterval(() => this.loadCounts(), COUNTS_EVERY_MS);
        onWillDestroy(() => clearInterval(timer));

        // Live updates: the server sends a notice (no details) whenever a
        // candidate's timeline, a callback or the candidate list changes.
        this.liveRefresh = useDebounced(() => this.onLiveChange(), 800);
        const onNotice = () => this.liveRefresh();
        const onVisible = () => document.visibilityState === "visible" && this.liveRefresh();
        this.bus.addChannel(LIVE_CHANNEL);
        this.bus.subscribe(LIVE_TYPE, onNotice);
        document.addEventListener("visibilitychange", onVisible); // catch up after being in the background
        onWillDestroy(() => {
            this.bus.unsubscribe(LIVE_TYPE, onNotice);
            this.bus.deleteChannel(LIVE_CHANNEL);
            document.removeEventListener("visibilitychange", onVisible);
        });
    }

    // ── Derived ─────────────────────────────────────────────────────────

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

    /** What the main pane and the information card show: a candidate on the
     *  inbox and on the Candidates lists, otherwise whatever the view lists. */
    get kind() {
        const view = this.state.view;
        if (view === "inbox" && this.pill === "unknown") {
            return "unknown"; // someone who wrote in on WhatsApp and isn't a candidate
        }
        return view === "inbox" || (view === "cand" && this.pill !== "stages") ? "candidate" : view;
    }

    /** The filters above the list. Only staff who may run ID checks get that one. */
    get pills() {
        const lists = this.state.counts.lists || {};
        return this.view.pills
            .filter(([id]) => id !== "idc" || this.state.boot.can_id_check)
            .map(([id, label]) => ({
                id, label, count: id === "idc" ? lists.id_open : id === "unknown" ? this.state.counts.unknown : 0,
            }));
    }

    get idSubs() {
        const lists = this.state.counts.lists || {};
        return ID_SUBS.map(([id, label, count]) => ({ id, label, count: lists[count] || 0 }));
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
        if (this.kind === "unknown") {
            return c.window_open ? false
                : _t("WhatsApp won't deliver a typed reply now: their last message was more than 24 hours ago.");
        }
        if (!c.phone) {
            return _t("This candidate has no phone number.");
        }
        if (this.channel === "whatsapp" && !c.window_open) {
            return _t("WhatsApp only allows a template now: their last message was more than 24 hours ago.");
        }
        return false;
    }

    // ── Assistant ───────────────────────────────────────────────────────

    /** The assistant's answers belong to one candidate; opening another starts clean. */
    get ai() {
        const ai = this.state.ai;
        const id = this.state.detail && this.state.detail.id;
        if (ai.forId !== id) {
            Object.assign(ai, { forId: id, summary: "", chat: [], question: "" });
        }
        return ai;
    }

    async aiCall(what, method, args) {
        const ai = this.ai;
        if (ai.busy) {
            return false;
        }
        const id = ai.forId;
        ai.busy = what;
        try {
            const result = await this.orm.call(WS, method, [id, ...args]);
            return this.state.ai.forId === id ? result : false; // the agent moved on meanwhile
        } finally {
            this.state.ai.busy = "";
        }
    }

    /** Put a drafted reply in the box for the agent to edit. Nothing is sent. */
    async draftReply() {
        if (this.composerLock) {
            return;
        }
        const result = await this.aiCall("draft", "ws_ai_draft", [this.channel]);
        if (result) {
            this.state.composer = result.text;
        }
    }

    async catchUp() {
        const result = await this.aiCall("summary", "ws_ai_summary", []);
        if (result) {
            this.ai.summary = result.text;
        }
    }

    async ask() {
        const ai = this.ai;
        const question = ai.question.trim();
        if (!question) {
            return;
        }
        const history = ai.chat.map((item) => ({ q: item.q, a: item.a }));
        const result = await this.aiCall("ask", "ws_ai_ask", [question, history]);
        if (result) {
            ai.chat.push({ q: question, a: result.answer });
            ai.question = "";
        }
    }

    onAskInput(ev) {
        this.ai.question = ev.target.value;
    }

    onAskKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.ask();
        }
    }

    /** Do the suggested next step with the button the screen already has. */
    nextStep() {
        const c = this.state.detail;
        const action = c.next_step && c.next_step.action;
        if (action === "draft") {
            this.setPane("thread");
            if (this.composerLock && c.phone) {
                this.setChannel("sms"); // WhatsApp is past its 24 hours; SMS has no such rule
            }
            return this.draftReply();
        }
        if (action === "reply") {
            return this.setPane("thread");
        }
        if (action === "cv_help") {
            return this.helpBuildCv();
        }
        if (action === "cv_link") {
            return this.candidateAction("action_resend_cv_link", c.id, _t("CV link queued"));
        }
        if (action === "jobs") {
            return this.candidateAction("action_c2w_send_jobs");
        }
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
    async loadList({ keep = false, quiet = false } = {}) {
        const view = this.state.view;
        const page = this.state.boot.page_size;
        const limit = keep ? Math.max(page, this.state.rows.length) : page;
        const [method, args] = this.view.list(this.pill, this.state.search, 0, limit, this.state.idSub);
        this.state.loadingList = !quiet;
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
        if (view === "side") {
            return; // the open chat is the agent's choice (or a new one), not the list's
        }
        const ids = this.state.rows.map((r) => r.id);
        // A candidate opened from another screen stays open even when the list
        // (the most recent 100) doesn't include them.
        const pinned = this.state.pinnedId && this.state.selId === this.state.pinnedId;
        if (!ids.includes(this.state.selId) && !pinned) {
            this.state.selId = ids.length ? ids[0] : false;
        }
        await this.loadDetail({ quiet });
    }

    async loadDetail({ quiet = false } = {}) {
        const id = this.state.selId;
        if (!id) {
            this.state.detail = false;
            return;
        }
        this.state.loadingDetail = !quiet;
        try {
            let detail;
            if (this.state.view === "cand" && this.pill === "stages") {
                const stage = this.state.rows.find((r) => r.id === id);
                detail = { ...stage, ...(await this.orm.call(WS, "ws_stage", [id, this.state.show, this.state.search])) };
            } else {
                detail = await this.orm.call(WS, this.kind === "unknown" ? "ws_unknown_thread" : this.view.detail, [id]);
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
        const [method, args] = this.view.list(this.pill, this.state.search, this.state.rows.length, page,
                                              this.state.idSub);
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

    /**
     * Something changed on the server. Reload quietly (no loading state), but
     * leave the open record alone while the agent is typing in its details or
     * has a dialog or the CV page open, so nothing they typed is lost.
     */
    async onLiveChange() {
        const busy = this.state.sending || this.state.cvHelp || this.state.loadingMore ||
            document.querySelector(".o_dialog") || document.activeElement?.closest(".o_c2w_info");
        if (busy || this.state.view === "side") {
            await this.loadCounts();
            return;
        }
        await Promise.all([this.loadList({ keep: true, quiet: true }), this.loadCounts()]);
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
        return item.view === "side" ? this.openSidekick() : this.go(item.view, item.pill);
    }

    /** Open a screen an answer or a list points at. */
    openScreen(open) {
        if (open.candidate_id) {
            return this.openCandidate(open.candidate_id);
        }
        if (open.sub) {
            this.state.idSub = open.sub;
        }
        return this.go(open.view, open.pill);
    }

    async setIdSub(sub) {
        this.state.idSub = sub;
        this.state.pinnedId = false;
        this.state.pane = "list";
        await this.loadList();
    }

    async setPill(pill) {
        const numbers = this.state.view === "inbox" && (pill === "unknown") !== (this.pill === "unknown");
        if ((this.state.view === "cand" && pill !== this.pill) || numbers) {
            // Stages and candidate lists are drawn differently: don't show one as the other while loading.
            Object.assign(this.state, { selId: false, detail: false, rows: [] });
        }
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
        this.state.side.error = "";
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

    /** Point the screen at what an alert is about; the next list load shows it. */
    applyTarget(target) {
        if (target.view) {
            // A list, or one record on it, that a dashboard tile points at.
            if (target.sub) {
                this.state.idSub = target.sub;
            }
            if (target.pill) {
                this.state.pills[target.view] = target.pill;
            }
            Object.assign(this.state, {
                view: target.view, search: "", detail: false, rows: [], composer: "",
                selId: target.sel || false, pinnedId: target.sel || false, pane: target.sel ? "thread" : "list",
            });
            return;
        }
        const number = target.unknown;
        Object.assign(this.state, {
            view: "inbox", search: "", detail: false, rows: [], composer: "",
            selId: target.candidate_id || number || false,
            pinnedId: target.candidate_id || number || false,
            pane: target.candidate_id || number ? "thread" : "list",
        });
        this.state.pills.inbox = number ? "unknown" : target.pill || "all";
    }

    async openTarget(target) {
        if (target.view === "side") {
            return this.openSidekick();
        }
        this.applyTarget(target);
        await Promise.all([this.loadList(), this.loadCounts()]);
    }

    /** "Dealt with": off the waiting list until they write again. */
    async unknownDone() {
        await this.orm.call(WS, "ws_unknown_done", [this.state.detail.id]);
        await this.refresh();
        this.alerts.refresh();
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
            this.state.detail = this.kind === "unknown"
                ? await this.orm.call(WS, "ws_unknown_send", [this.state.detail.id, text])
                : await this.orm.call(WS, "ws_send", [this.state.detail.id, text, this.channel]);
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

    // ── ID check, on the candidate's information card ───────────────────

    /** The same button as the candidate form. The candidate stays open even
     *  when the result takes them off the list being shown. */
    runIdCheck() {
        this.state.pinnedId = this.state.detail.id;
        return this.candidateAction("action_c2w_id_check");
    }

    async updateIdNumber() {
        await this.action.doAction("chat2work.action_chat2work_id_update", {
            additionalContext: { default_candidate_id: this.state.detail.id },
            onClose: () => this.refresh(),
        });
    }

    async refreshBalance() {
        await this.orm.call("chat2work.verify.account", "action_refresh_balance", [[this.state.detail.id_check.account.id]]);
        await this.loadDetail({ quiet: true });
    }

    // ── Sidekick ────────────────────────────────────────────────────────

    newChat() {
        return { id: false, name: _t("New chat"), candidate: false, messages: [] };
    }

    /** Show the sidekick: on `chat` (one about a candidate, from their
     *  information card), otherwise on a new chat with today's suggestions. */
    async openSidekick(chat = false) {
        Object.assign(this.state, {
            view: "side", search: "", pane: "thread", pinnedId: false, rows: [],
            selId: chat ? chat.id : false, detail: chat || this.newChat(),
        });
        Object.assign(this.state.side, { question: "", pending: "", error: "" });
        const [start] = await Promise.all([this.orm.call(WS, "ws_sidekick_start", []), this.loadList()]);
        this.state.side.start = start;
    }

    async askSidekick() {
        const chat = await this.orm.call(WS, "ws_sidekick_for_candidate", [this.state.detail.id]);
        if (chat) {
            await this.openSidekick(chat);
        }
    }

    /** The chat as the thread draws it: a divider where the day changes, and
     *  each answer's text split into paragraphs and lists. */
    get sideThread() {
        const items = [];
        let lastDay = "";
        for (const message of this.state.detail.messages || []) {
            const day = this.day(message.at);
            if (day !== lastDay) {
                items.push({ key: "d" + message.id, kind: "day", label: day });
                lastDay = day;
            }
            const answer = message.role === "sidekick";
            items.push({ ...message, key: "m" + message.id, kind: answer ? "a" : "q",
                         blocks: answer ? this.textBlocks(message.text) : [] });
        }
        return items;
    }

    /** Plain text as blocks: lines starting "1." or "-" become a list, the rest paragraphs. */
    textBlocks(text) {
        const blocks = [];
        for (const line of (text || "").split("\n").map((l) => l.trim()).filter(Boolean)) {
            const item = line.match(/^(\d+[.)]|[-•*])\s+(.*)$/);
            const kind = !item ? "p" : /\d/.test(item[1]) ? "ol" : "ul";
            const last = blocks[blocks.length - 1];
            if (item && last && last.kind === kind) {
                last.items.push(item[2]);
            } else {
                blocks.push(item ? { kind, items: [item[2]] } : { kind, text: line });
            }
        }
        return blocks;
    }

    /** How long since `value`: "19 h", "1 d 3 h", "4 d". */
    waited(value) {
        if (!value) {
            return "";
        }
        const minutes = Math.max(0, Math.floor(luxon.DateTime.local().diff(deserializeDateTime(value), "minutes").minutes));
        const d = Math.floor(minutes / 1440);
        const h = Math.floor((minutes % 1440) / 60);
        if (d) {
            return h && d < 3 ? _t("%(d)s d %(h)s h", { d, h }) : _t("%s d", d);
        }
        return h ? _t("%s h", h) : _t("%s min", minutes);
    }

    draftMeta(draft) {
        const length = draft.text.length;
        return draft.channel === "sms"
            ? _t("SMS · %(length)s of %(limit)s characters", { length, limit: 160 })
            : _t("WhatsApp · %s characters", length);
    }

    get sidePlaceholder() {
        const chat = this.state.detail;
        if (chat.candidate) {
            return _t("Ask about %s…", chat.candidate.first_name);
        }
        return chat.id ? _t("Ask a follow-up…") : _t("Ask about a candidate, a callback, a job…");
    }

    async newSidekickChat() {
        this.state.selId = false;
        this.state.detail = this.newChat();
        this.state.pane = "thread";
        Object.assign(this.state.side, { question: "", error: "" });
        this.state.side.start = await this.orm.silent.call(WS, "ws_sidekick_start", []);
    }

    onSideInput(ev) {
        this.state.side.question = ev.target.value;
    }

    onSideKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.sideAsk();
        }
    }

    /** Ask what is typed, or `text` (a suggestion or a follow-up). The answer
     *  comes back as the whole chat; an error leaves the question in the box. */
    async sideAsk(text = null) {
        const side = this.state.side;
        const question = (text === null ? side.question : text).trim();
        if (!question || side.busy || !side.start || !side.start.ai) {
            return;
        }
        const chat = this.state.detail;
        Object.assign(side, { busy: true, pending: question, error: "", question: "" });
        let result;
        try {
            result = await this.orm.silent.call(WS, "ws_sidekick_ask",
                                                [chat.id, question, chat.candidate ? chat.candidate.id : false]);
        } catch {
            result = { error: _t("The sidekick couldn't answer just now. Your question is still here: try again.") };
        } finally {
            Object.assign(side, { busy: false, pending: "" });
        }
        const here = this.state.view === "side" && this.state.detail === chat;
        if (result.error) {
            if (here) {
                Object.assign(side, { error: result.error, question });
            }
            return;
        }
        if (here) {
            this.state.selId = result.id;
            this.state.detail = result;
        }
        if (this.state.view === "side") {
            await this.loadList({ keep: true, quiet: true });
        }
    }

    /** Put a draft in the candidate's reply box for the agent to edit and send:
     *  by SMS when it was written as one or WhatsApp is past its 24 hours. */
    async useDraft(draft) {
        const candidate = this.state.detail.candidate;
        await this.openCandidate(candidate.id);
        const c = this.state.detail;
        if (!c || c.id !== candidate.id) {
            return;
        }
        if (c.whatsapp) {
            this.setChannel(draft.channel === "sms" || !c.window_open ? "sms" : "whatsapp");
        }
        this.state.composer = draft.text;
    }

    async copyDraft(draft) {
        await browser.navigator.clipboard.writeText(draft.text);
        this.notification.add(_t("Draft copied"), { type: "success" });
    }
}

registry.category("actions").add("chat2work_workspace", Chat2workWorkspace);
