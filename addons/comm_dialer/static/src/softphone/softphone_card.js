/** @odoo-module **/

import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const KEYS = [
    ["1", ""], ["2", "ABC"], ["3", "DEF"], ["4", "GHI"], ["5", "JKL"], ["6", "MNO"],
    ["7", "PQRS"], ["8", "TUV"], ["9", "WXYZ"], ["*", ""], ["0", "+"], ["#", ""],
];
const TABS = [["recent", "Recent", "fa-history"], ["keypad", "Keypad", "fa-th"], ["activities", "Activities", "fa-clock-o"]];

/** "4 min 12 s" / "58 s" */
export function phoneDuration(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

/** "02:41" */
export function phoneClock(ms) {
    const s = Math.max(0, Math.floor((ms || 0) / 1000));
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    return `${mm}:${String(s % 60).padStart(2, "0")}`;
}

/** Initials + a steady colour for someone's avatar tile. */
export function phoneAvatar(name, known = true) {
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
export function phoneDays(rows) {
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

/** The softphone as one card (Odoo 20 phone widget look): status header, body,
 *  three tabs. Registered as a main component so it renders at the app root,
 *  above all content and outside the navbar's stacking context. */
export class DialerSoftphoneCard extends Component {
    static template = "comm_dialer.SoftphoneCard";
    static props = {};

    setup() {
        this.sp = useService("dialer_softphone");
        this.action = useService("action");
        this.state = useState(this.sp.state);
        this.keys = KEYS;
        this.tabs = TABS;
        this.ui = useState({
            tab: "keypad",
            number: "",
            search: "",
            calls: [],
            contacts: [],
            activities: [],
            loading: false,
            // In-call sub screen: call | keypad | transfer | script | picker
            sub: "call",
            tones: "",
            picker: null,
            items: [],
            answer: "",
            targets: [],
            target: null,
            mode: "blind",
            busy: false,
            now: Date.now(),
        });
        this.searchSeq = 0;

        // A call starting or ending resets the in-call screen; a script that
        // starts on its own (campaign suggestion) does not take the screen over.
        useEffect(
            (live) => {
                this.ui.sub = "call";
                this.ui.tones = "";
                this.ui.picker = null;
                if (!live && this.state.dialerOpen && this.ui.tab === "recent") {
                    this.loadRecent();
                }
            },
            () => [this.state.live]
        );
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
            () => [this.state.since]
        );
        // Opening the card refreshes whichever list is showing.
        useEffect(
            (open) => {
                if (open && !this.state.live) {
                    this.refreshTab();
                }
            },
            () => [this.state.dialerOpen]
        );
        onWillUnmount(() => clearTimeout(this.searchTimer));
    }

    // ── What to show ────────────────────────────────────────────────────
    get live() {
        return this.state.live;
    }

    get incoming() {
        return this.state.status === "ringing" && this.state.manual;
    }

    get canCall() {
        return this.state.status === "registered";
    }

    get head() {
        const st = this.state.status;
        if (this.live) {
            if (st === "ringing") {
                return { dot: "ring", label: "Ringing", sub: "" };
            }
            if (st === "incall") {
                return { dot: "ok", label: this.state.held ? "On hold" : "On call", sub: "" };
            }
            return { dot: "away", label: st === "calling" ? "Calling" : "Connecting", sub: "" };
        }
        return {
            registered: { dot: "ok", label: "Available", sub: "Softphone ready" },
            connecting: { dot: "away", label: "Connecting", sub: "Reaching the phone server" },
            unregistered: { dot: "off", label: "Not registered", sub: "" },
            failed: { dot: "off", label: "Not registered", sub: "Phone server unreachable" },
        }[st] || { dot: "off", label: "Not connected", sub: "" };
    }

    get banner() {
        return {
            connecting: { text: "Connecting to the phone server…", retry: false, bad: false },
            unregistered: { text: "Not registered with the phone server.", retry: true, bad: true },
            failed: { text: "Can't reach the phone server. Check the VoIP connection.", retry: true, bad: true },
            idle: { text: "The softphone isn't connected yet.", retry: true, bad: false },
        }[this.state.status] || null;
    }

    get callState() {
        const st = this.state.status;
        if (st === "incall") {
            const clock = phoneClock(this.ui.now - this.state.since);
            return this.state.held ? `On hold · ${clock}` : `On call · ${clock}`;
        }
        return { ringing: "Incoming call", calling: "Calling…", connecting: "Connecting…" }[st] || "";
    }

    get who() {
        const name = this.state.caller || this.state.number || "Call";
        const number = this.state.number && this.state.number !== name ? this.state.number : "";
        return { name, number, av: phoneAvatar(name, !!this.state.partnerId || name !== this.state.number) };
    }

    get days() {
        return phoneDays(this.ui.calls).map((day) => ({
            label: day.label,
            rows: day.rows.map((c) => Object.assign(c, { av: phoneAvatar(c.name, !!c.partner_id), line: this.callLine(c) })),
        }));
    }

    callLine(c) {
        if (c.direction === "outgoing") {
            return { text: `↗ Outgoing · ${c.answered ? phoneDuration(c.duration) : "no answer"}`, miss: false };
        }
        return c.answered
            ? { text: `↙ Incoming · ${phoneDuration(c.duration)}`, miss: false }
            : { text: "↙ Missed", miss: true };
    }

    avatar(name) {
        return phoneAvatar(name);
    }

    // ── Header ──────────────────────────────────────────────────────────
    minimise() {
        this.sp.toggleDialer();
    }

    reopen() {
        if (!this.state.dialerOpen) {
            this.sp.toggleDialer();
        }
    }

    expand() {
        this.action.doAction("comm_chatbot_voip.action_comm_voip_call");
    }

    retry() {
        this.sp.retry();
    }

    // ── Tabs ────────────────────────────────────────────────────────────
    setTab(tab) {
        this.ui.tab = tab;
        this.refreshTab();
    }

    refreshTab() {
        if (this.ui.tab === "recent") {
            this.loadRecent();
        } else if (this.ui.tab === "activities") {
            this.loadActivities();
        }
    }

    async loadRecent() {
        const seq = ++this.searchSeq;
        this.ui.loading = true;
        try {
            const res = await this.sp.recent(this.ui.search);
            if (seq === this.searchSeq) {
                this.ui.calls = res.calls || [];
                this.ui.contacts = res.contacts || [];
            }
        } catch {
            if (seq === this.searchSeq) {
                this.ui.calls = [];
                this.ui.contacts = [];
            }
        } finally {
            if (seq === this.searchSeq) {
                this.ui.loading = false;
            }
        }
    }

    onSearch(ev) {
        this.ui.search = ev.target.value;
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.loadRecent(), 250);
    }

    async loadActivities() {
        this.ui.loading = true;
        try {
            this.ui.activities = await this.sp.activities();
        } catch {
            this.ui.activities = [];
        } finally {
            this.ui.loading = false;
        }
    }

    // Calling from a list: dial at once when registered, else show the keypad
    // with the number filled in so the connection problem is in front of them.
    call(number, name) {
        if (!number) {
            return;
        }
        if (this.canCall) {
            this.sp.dial(number, name);
        } else {
            this.ui.number = number;
            this.ui.tab = "keypad";
        }
    }

    openContact(partnerId) {
        if (partnerId) {
            this.action.doAction({
                type: "ir.actions.act_window", res_model: "res.partner", res_id: partnerId,
                views: [[false, "form"]], target: "current",
            });
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

    // ── Keypad ──────────────────────────────────────────────────────────
    press(key) {
        this.ui.number += key;
    }

    backspace() {
        this.ui.number = this.ui.number.slice(0, -1);
    }

    callNow() {
        const number = this.ui.number.trim();
        if (this.canCall && number) {
            this.sp.dial(number);
            this.ui.number = "";
        }
    }

    onNumberKeydown(ev) {
        if (ev.key === "Enter") {
            this.callNow();
        }
    }

    // ── In call ─────────────────────────────────────────────────────────
    accept() {
        this.sp.accept();
    }

    hangup() {
        this.sp.hangup();
    }

    toggleMute() {
        this.sp.toggleMute();
    }

    toggleHold() {
        this.sp.toggleHold();
    }

    toggleRecord() {
        this.sp.toggleRecord();
    }

    showSub(sub) {
        this.ui.sub = sub;
    }

    tone(key) {
        this.ui.tones += key;
        this.sp.sendDtmf(key);
    }

    // Script: open the follower when one is running, else pick one.
    script() {
        if (this.state.script) {
            this.ui.sub = "script";
        } else {
            this.openPicker("script");
        }
    }

    async openPicker(kind) {
        this.ui.sub = "picker";
        this.ui.picker = kind;
        this.ui.items = [];
        this.ui.loading = true;
        try {
            this.ui.items = kind === "script" ? await this.sp.scriptOptions() : await this.sp.campaignOptions();
        } catch {
            this.ui.items = [];
        } finally {
            this.ui.loading = false;
        }
    }

    pick(item) {
        const kind = this.ui.picker;
        this.ui.picker = null;
        if (kind === "script") {
            this.sp.startScript(item.id, item.name);
            this.ui.sub = "script";
        } else {
            if (!item.already) {
                this.sp.addToCampaign(item.id);
            }
            this.ui.sub = "call";
        }
    }

    scriptAnswer(text) {
        text = (text || "").trim();
        if (text) {
            this.ui.answer = "";
            this.sp.scriptTurn(text);
        }
    }

    onScriptKeydown(ev) {
        if (ev.key === "Enter") {
            this.scriptAnswer(this.ui.answer);
        }
    }

    closeScript() {
        this.sp.closeScript();
        this.ui.sub = "call";
    }

    // ── Transfer ────────────────────────────────────────────────────────
    async openTransfer() {
        this.ui.sub = "transfer";
        this.ui.target = null;
        this.ui.mode = "blind";
        this.ui.targets = [];
        this.ui.loading = true;
        try {
            this.ui.targets = await this.sp.transferTargets();
        } catch {
            this.ui.targets = [];
        } finally {
            this.ui.loading = false;
        }
    }

    async doTransfer() {
        if (!this.ui.target || this.ui.busy) {
            return;
        }
        this.ui.busy = true;
        try {
            const ok = await this.sp.transfer(this.ui.target, this.ui.mode);
            if (ok && this.ui.mode === "blind") {
                this.ui.sub = "call";
            }
        } finally {
            this.ui.busy = false;
        }
    }

    transferDecide(complete) {
        this.sp.transferDecide(complete);
    }
}

registry.category("main_components").add("comm_dialer.softphone_card", {
    Component: DialerSoftphoneCard,
});
