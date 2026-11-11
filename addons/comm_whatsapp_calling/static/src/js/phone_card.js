/** @odoo-module **/

import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// The helpers below mirror comm_dialer's softphone_card.js. They are copied,
// not imported: comm_dialer depends on this addon, not the other way round.

const KEYS = [
    ["1", ""], ["2", "ABC"], ["3", "DEF"], ["4", "GHI"], ["5", "JKL"], ["6", "MNO"],
    ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"], ["*", ""], ["0", "+"], ["#", ""],
];
const TABS = [["recent", "Recent", "fa-history"], ["keypad", "Keypad", "fa-th"], ["activities", "Activities", "fa-clock-o"]];
const PRESENCES = [
    { key: "available", label: "Available", dot: "ok" },
    { key: "away", label: "Away", dot: "away" },
    { key: "dnd", label: "Do not disturb", dot: "off" },
];
const PERMISSION_CHIPS = {
    granted: { label: "Can be called", cls: "ok" },
    pending: { label: "Asked, no reply yet", cls: "warn" },
    declined: { label: "Declined calls", cls: "bad" },
    expired: { label: "Permission expired", cls: "warn" },
};

/** "4 min 12 s" / "58 s" */
function phoneDuration(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

/** "02:41" */
function phoneClock(ms) {
    const s = Math.max(0, Math.floor((ms || 0) / 1000));
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    return `${mm}:${String(s % 60).padStart(2, "0")}`;
}

/** Initials + a steady colour for someone's avatar tile. */
function phoneAvatar(name, known = true) {
    const label = (name || "").trim();
    if (!known || !label || /^[+\d\s()-]+$/.test(label)) {
        return { text: "?", cls: "u" };
    }
    const parts = label.split(/\s+/);
    const text = ((parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
    let sum = 0;
    for (const ch of label) {
        sum += ch.charCodeAt(0);
    }
    const n = sum % 6;
    return { text, cls: n ? `c${n}` : "" };
}

/** Group rows that carry a server datetime in `at` under Today / Yesterday / date. */
function phoneDays(rows) {
    const days = [];
    const today = luxon.DateTime.local().startOf("day");
    for (const row of rows) {
        const at = row.at ? deserializeDateTime(row.at) : null;
        let label = "Earlier";
        if (at) {
            const gap = Math.round(today.diff(at.startOf("day"), "days").days);
            label = gap <= 0 ? "Today" : gap === 1 ? "Yesterday" : at.toFormat("d LLL yyyy");
        }
        const item = Object.assign({}, row, { time: at ? at.toFormat("HH:mm") : "" });
        const last = days[days.length - 1];
        if (last && last.label === label) {
            last.rows.push(item);
        } else {
            days.push({ label, rows: [item] });
        }
    }
    return days;
}

function presenceOf(key) {
    return PRESENCES.find((p) => p.key === key) || PRESENCES[0];
}

/** WhatsApp calling as one card (Odoo 20 phone widget look): status header,
 *  body, three tabs. Everything it prints comes from the calling service's
 *  `state`; everything it does goes through the service's `card` actions. */
export class WhatsAppPhoneCard extends Component {
    static template = "comm_whatsapp_calling.PhoneCard";
    static props = {};

    setup() {
        this.wa = useService("comm_whatsapp_calling");
        this.action = useService("action");
        this.card = this.wa.card;
        this.state = useState(this.wa.state);
        this.keys = KEYS;
        this.tabs = TABS;
        this.presences = PRESENCES;
        this.ui = useState({
            search: "",
            calls: [],
            contacts: [],
            activities: [],
            loading: false,
            failed: false,
            menu: false,        // presence menu is open
            answer: "",         // script follower input
            confirmEnd: false,  // "End script and call" was clicked once
            playing: null,      // recording id being played
            second: false,      // a VoIP card is open too: sit to its left
            pillSecond: false,  // a VoIP card or pill holds the corner: stack above it
            now: Date.now(),
        });
        this.searchSeq = 0;
        this.audio = null;

        // Tick the call timer only while a call is connected.
        useEffect(
            (since) => {
                if (!since) {
                    return;
                }
                this.ui.now = Date.now();
                const timer = setInterval(() => (this.ui.now = Date.now()), 1000);
                return () => clearInterval(timer);
            },
            () => [this.state.call && this.state.call.startTime]
        );
        // Showing a list (card opened, tab changed, a call just ended) refreshes it.
        useEffect(
            (open, idle) => {
                if (open && idle) {
                    this.refreshTab();
                }
            },
            () => [this.state.open, this.idle, this.state.tab]
        );
        // Make room for the VoIP softphone whenever both are on screen,
        // whichever opened first. Its card is not ours to watch, so look for it.
        useEffect(
            (shown) => {
                if (!shown) {
                    return;
                }
                const check = () => {
                    this.ui.second = !!document.querySelector(".o_phone_card.o_phone_voip");
                    this.ui.pillSecond = !!document.querySelector(
                        ".o_phone_card.o_phone_voip, .o_phone_pill:not(.o_phone_wa)");
                };
                check();
                const observer = new MutationObserver(check);
                observer.observe(document.body, { childList: true, subtree: true });
                return () => observer.disconnect();
            },
            () => [this.state.open || this.busy || !!this.state.wrapup]
        );
        // A call starting or ending resets what belongs to the previous one.
        useEffect(
            () => {
                this.ui.answer = "";
                this.ui.confirmEnd = false;
                this.ui.menu = false;
                this.stopRecording();
            },
            () => [this.busy]
        );
        onWillUnmount(() => {
            clearTimeout(this.searchTimer);
            clearTimeout(this.lookupTimer);
            this.stopRecording();
        });
    }

    // ── What to show ────────────────────────────────────────────────────
    /** A call is ringing, being set up or connected. */
    get busy() {
        const s = this.state;
        return !!(s.incoming || s.call || s.transferRequest || s.connecting);
    }

    /** Nothing is in front of the three tabs. */
    get idle() {
        const s = this.state;
        return !this.busy && !s.wrapup && !s.permission && !s.picker;
    }

    get ringing() {
        return !!(this.state.incoming || (this.state.transferRequest && !this.state.call));
    }

    get head() {
        const s = this.state;
        if (s.incoming) {
            return { live: true, dot: "ring", label: "Ringing" };
        }
        if (s.call) {
            return s.call.startTime
                ? { live: true, dot: "ok", label: "On call" }
                : { live: true, dot: "away", label: "Calling" };
        }
        if (s.transferRequest) {
            return { live: true, dot: "ring", label: "Ringing" };
        }
        if (s.connecting) {
            return { live: true, dot: "away", label: s.connecting.label };
        }
        if (s.wrapup) {
            return { live: true, dot: "away", label: "Wrapping up" };
        }
        const presence = presenceOf(s.presence);
        return { live: false, dot: presence.dot, label: presence.label };
    }

    /** "In call for 03:18" */
    get callState() {
        const call = this.state.call;
        if (!call) {
            return "";
        }
        return call.startTime ? `In call for ${phoneClock(this.ui.now - call.startTime)}` : "Calling…";
    }

    /** Whoever the pill names while the card is minimised. */
    get pillName() {
        const s = this.state;
        const who = s.incoming || s.call || s.transferRequest || s.connecting || s.wrapup;
        return who ? who.name : "";
    }

    get days() {
        return phoneDays(this.ui.calls).map((day) => ({
            label: day.label,
            rows: day.rows.map((c) => Object.assign(c, { av: phoneAvatar(c.name, !!c.partnerId), line: this.callLine(c) })),
        }));
    }

    callLine(c) {
        if (c.direction === "outgoing") {
            return { text: `↗ Outgoing · ${c.duration ? phoneDuration(c.duration) : "no answer"}`, miss: false };
        }
        if (c.status === "declined") {
            return { text: "↙ Declined", miss: true };
        }
        if (c.missed) {
            return { text: "↙ Missed", miss: true };
        }
        return { text: c.duration ? `↙ Answered · ${phoneDuration(c.duration)}` : "↙ Answered", miss: false };
    }

    get keypadChip() {
        return PERMISSION_CHIPS[this.state.keypad.permission] || null;
    }

    /** `who` is any of the state objects that carry a name and a number. */
    avatar(who) {
        return phoneAvatar(who.name, !!who.partnerId || who.name !== who.number);
    }

    // ── Header ──────────────────────────────────────────────────────────
    toggleMenu() {
        // A real click: the moment to ask for desktop notifications, which
        // browsers refuse when asked from the bus event of a ringing call.
        this.wa.ensureNotificationPermission();
        this.ui.menu = !this.ui.menu;
    }

    closeMenu() {
        this.ui.menu = false;
    }

    setPresence(key) {
        this.ui.menu = false;
        this.card.setPresence(key);
    }

    allCalls() {
        this.action.doAction("comm_whatsapp_calling.action_whatsapp_call_log");
    }

    // ── Tabs ────────────────────────────────────────────────────────────
    setTab(tab) {
        this.state.tab = tab;
        if (tab === "keypad") {
            this.card.loadAccounts();
        }
    }

    refreshTab() {
        if (this.state.tab === "recent") {
            this.loadRecent();
        } else if (this.state.tab === "activities") {
            this.loadActivities();
        }
    }

    async loadRecent() {
        const seq = ++this.searchSeq;
        this.ui.loading = true;
        this.ui.failed = false;
        this.card.refreshMissed();
        let calls = [];
        let contacts = [];
        let failed = false;
        try {
            [calls, contacts] = await Promise.all([
                this.card.recentCalls(this.ui.search),
                this.card.matchingContacts(this.ui.search),
            ]);
        } catch {
            failed = true;
        }
        if (seq === this.searchSeq) {
            this.ui.calls = calls;
            this.ui.contacts = contacts;
            this.ui.failed = failed;
            this.ui.loading = false;
        }
    }

    onSearch(ev) {
        this.ui.search = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.loadRecent(), 300);
    }

    async loadActivities() {
        this.ui.loading = true;
        try {
            this.ui.activities = await this.card.activities();
        } catch {
            this.ui.activities = [];
        } finally {
            this.ui.loading = false;
        }
    }

    /** Ring someone from a list row. */
    call(row) {
        if (row.number) {
            this.card.placeCall({
                toNumber: row.number,
                partnerId: row.partnerId || null,
                partnerName: row.name || row.number,
            });
        }
    }

    callActivity(a) {
        this.call({
            number: a.number,
            name: a.name,
            partnerId: a.res_model === "res.partner" ? a.res_id : null,
        });
    }

    /** Put a row's number on the keypad instead of ringing straight away. */
    toKeypad(number) {
        if (number) {
            this.card.setKeypadNumber(number);
            this.setTab("keypad");
        }
    }

    openRecord(model, id) {
        if (model && id) {
            this.action.doAction({
                type: "ir.actions.act_window", res_model: model, res_id: id,
                views: [[false, "form"]], target: "current",
            });
        }
    }

    // ── Recordings ──────────────────────────────────────────────────────
    // The dedicated streaming route, not /web/content: it plays inline for
    // anyone who can read the call; download stays gated server-side.
    recordingUrl(id) {
        return `/whatsapp/call/recording/${id}`;
    }

    playRecording(id) {
        if (this.ui.playing === id) {
            this.stopRecording();
            return;
        }
        this.stopRecording();
        const audio = new Audio(this.recordingUrl(id));
        const done = () => {
            if (this.audio === audio) {
                this.audio = null;
                this.ui.playing = null;
            }
        };
        audio.addEventListener("ended", done);
        this.audio = audio;
        this.ui.playing = id;
        // A browser that can't play it in the card gets it in a new tab.
        audio.play().catch(() => {
            if (this.audio === audio) {
                done();
                this.openRecording(id);
            }
        });
    }

    stopRecording() {
        if (this.audio) {
            this.audio.pause();
            this.audio = null;
        }
        this.ui.playing = null;
    }

    openRecording(id) {
        window.open(this.recordingUrl(id), "_blank");
    }

    // ── Keypad ──────────────────────────────────────────────────────────
    onNumberInput(ev) {
        this.setNumber(ev.target.value);
    }

    // Look the number up once the agent pauses typing.
    setNumber(number) {
        this.state.keypad.number = number;
        clearTimeout(this.lookupTimer);
        this.lookupTimer = setTimeout(() => this.card.lookupKeypadNumber(), 400);
    }

    press(key) {
        this.setNumber(this.state.keypad.number + key);
    }

    backspace() {
        this.setNumber(this.state.keypad.number.slice(0, -1));
    }

    onNumberKeydown(ev) {
        if (ev.key === "Enter") {
            this.card.dialFromKeypad();
        }
    }

    onAccountChange(ev) {
        this.state.keypad.accountId = Number(ev.target.value) || null;
        this.card.lookupKeypadNumber();
    }

    // ── During a call ───────────────────────────────────────────────────
    scriptAnswer(text) {
        text = (text || "").trim();
        if (text) {
            this.ui.answer = "";
            this.card.scriptAnswer(text);
        }
    }

    onScriptKeydown(ev) {
        if (ev.key === "Enter") {
            this.scriptAnswer(this.ui.answer);
        }
    }

    // Ending the script ends the call with it, so it takes two clicks.
    endScript() {
        if (this.ui.confirmEnd) {
            this.ui.confirmEnd = false;
            this.card.endScript();
        } else {
            this.ui.confirmEnd = true;
        }
    }

    backToCall() {
        this.ui.confirmEnd = false;
        this.card.showScript(false);
    }

    selectTeam(team) {
        if (team.available) {
            this.state.transfer.teamId = team.id;
        }
    }
}

registry.category("main_components").add("comm_whatsapp_calling.phone_card", {
    Component: WhatsAppPhoneCard,
});

/** Systray: the one WhatsApp calling icon, with the presence dot and the
 *  missed-calls count. Clicking it opens or closes the card. */
export class WhatsAppPhoneSystray extends Component {
    static template = "comm_whatsapp_calling.PhoneSystray";
    static props = {};

    setup() {
        this.wa = useService("comm_whatsapp_calling");
        this.state = useState(this.wa.state);
    }

    get dot() {
        const s = this.state;
        if (s.incoming || s.transferRequest) {
            return "ring";
        }
        return presenceOf(s.presence).dot;
    }

    get title() {
        const missed = this.state.missed ? ` · ${this.state.missed} missed` : "";
        return `WhatsApp calls · ${presenceOf(this.state.presence).label}${missed}`;
    }

    get missed() {
        return this.state.missed > 99 ? "99+" : this.state.missed;
    }

    toggle() {
        // A real click: ask for desktop notifications before a call ever rings.
        this.wa.ensureNotificationPermission();
        this.wa.card.toggleCard();
    }
}

registry.category("systray").add(
    "comm_whatsapp_calling.phone",
    { Component: WhatsAppPhoneSystray },
    { sequence: 21 }
);
