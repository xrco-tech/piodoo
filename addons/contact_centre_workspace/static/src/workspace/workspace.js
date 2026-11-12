/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chatter } from "@mail/chatter/web_portal/chatter";

const { DateTime } = luxon;
const WS = "contact.centre.workspace";
const CONTACT = "contact.centre.contact";
const PAGE = 40;
const BADGE = { whatsapp: "WA", sms: "SMS", voice: "Tel", email: "@" };
const CHANNEL = { whatsapp: "WhatsApp", sms: "SMS", voice: _t("Call"), email: _t("Email") };

/** The Contact Centre inbox as a workspace: rail, list card, thread, information card. */
export class ContactCentreWorkspace extends Component {
    static template = "contact_centre_workspace.Workspace";
    static components = { Chatter };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.bus = useService("bus_service");
        this.notification = useService("notification");
        // Both are optional: the phone card owns WhatsApp calls and their
        // script, the softphone owns VoIP calls.
        this.calling = this.env.services.comm_whatsapp_calling || null;
        this.softphone = this.env.services.dialer_softphone || null;
        this.phone = this.calling ? useState(this.calling.state) : { call: null, script: null };

        const params = this.props.action.params || {};
        this.campaignId = params.campaign_id || false;
        this.campaignName = params.campaign_name || "";

        this.state = useState({
            boot: { rail: [], dispositions: [], counts: { unread: 0 }, ai: false, voip: false, me: { name: "", initials: "" } },
            pill: "all",
            search: "",
            rows: [],
            more: false,
            loadingList: true,
            sel: false,
            thread: null,
            loadingThread: false,
            text: "",
            channel: "whatsapp",
            sending: false,
            pane: "list",          // phones show one pane at a time
            infoOpen: true,
            tab: "conversation",   // conversation | script | notes
            menu: null,            // call | template
            voiceBots: null,
            tpl: { channel: "whatsapp", list: [], id: false, sending: false, error: "" },
            analysing: false,
            transcribing: false,
            scriptText: "",
            now: Date.now(),
        });

        this.threadRef = useRef("thread");
        this.composerRef = useRef("composer");
        useEffect(() => this.scrollToEnd(), () => [this.state.thread && this.state.thread.messages]);
        useEffect(() => this.growComposer(), () => [this.state.text]);
        // A script starting brings its tab forward; one ending puts the card back.
        useEffect(
            (running) => {
                if (running) {
                    this.state.tab = "script";
                    this.state.infoOpen = true;
                } else if (this.state.tab === "script") {
                    this.state.tab = "conversation";
                }
            },
            () => [!!this.phone.script]
        );

        this.refresh = useDebounced(() => this.reload(), 400);
        this.searchLater = useDebounced(() => this.loadList(), 300);
        this.onBus = (payload) => {
            this.lastBusContact = payload && payload.contact_id;
            this.refresh();
        };
        this.bus.subscribe("contact_centre_new_message", this.onBus);
        this.bus.start();
        const tick = setInterval(() => {
            if (this.phone.call) {
                this.state.now = Date.now();
            }
        }, 1000);
        onWillDestroy(() => {
            this.bus.unsubscribe("contact_centre_new_message", this.onBus);
            clearInterval(tick);
        });

        onWillStart(async () => {
            const [boot] = await Promise.all([this.orm.call(WS, "ws_boot", []), this.loadList()]);
            this.state.boot = boot;
            if (params.contact_id) {
                await this.open(params.contact_id);
            }
        });
    }

    // ── Loading ──────────────────────────────────────────────────────────
    async loadList(limit = PAGE) {
        this.state.loadingList = true;
        try {
            const result = await this.orm.call(WS, "ws_list", [], {
                pill: this.state.pill, search: this.state.search, offset: 0, limit, campaign_id: this.campaignId,
            });
            this.state.rows = result.rows;
            this.state.more = result.more;
        } finally {
            this.state.loadingList = false;
        }
    }

    async loadMore() {
        const result = await this.orm.call(WS, "ws_list", [], {
            pill: this.state.pill, search: this.state.search, offset: this.state.rows.length, limit: PAGE,
            campaign_id: this.campaignId,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async loadThread(id) {
        const first = !this.state.thread || this.state.thread.id !== id;
        if (first) {
            this.state.loadingThread = true;
        }
        try {
            const thread = await this.orm.call(WS, "ws_thread", [id]);
            if (this.state.sel !== id) {
                return; // another conversation was opened meanwhile
            }
            this.state.thread = thread;
            if (first) {
                this.state.channel = thread.channel;
            }
        } finally {
            this.state.loadingThread = false;
        }
    }

    /** A message came in or went out somewhere: bring the screen up to date quietly. */
    async reload() {
        // The open conversation first: reading it marks it as seen, so the
        // list and the counts that follow no longer call it unread.
        if (this.state.sel && (!this.lastBusContact || this.lastBusContact === this.state.sel)) {
            await this.loadThread(this.state.sel);
        }
        this.lastBusContact = false;
        await Promise.all([
            this.loadList(Math.max(PAGE, this.state.rows.length)),
            this.orm.call(WS, "ws_counts", []).then((counts) => { this.state.boot.counts = counts; }),
        ]);
    }

    async open(id) {
        this.state.sel = id;
        this.state.pane = "thread";
        this.state.menu = null;
        this.state.text = "";
        if (this.state.tab === "notes") {
            this.state.tab = "conversation";
        }
        await this.loadThread(id);
        // Opening it marks it as seen: the counts drop.
        const row = this.state.rows.find((r) => r.id === id);
        if (row && row.unread) {
            row.unread = 0;
            this.state.boot.counts = await this.orm.call(WS, "ws_counts", []);
        }
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        return [
            { key: "all", label: _t("All") },
            { key: "unread", label: _t("Unread"), count: this.state.boot.counts.unread },
            { key: "open", label: _t("Open") },
            { key: "pending", label: _t("Pending") },
            { key: "resolved", label: _t("Resolved") },
            { key: "whatsapp", label: "WhatsApp" },
            { key: "sms", label: "SMS" },
            { key: "voice", label: _t("Calls") },
        ];
    }

    setPill(key) {
        this.state.pill = key;
        this.loadList();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchLater();
    }

    badge(channel) {
        return BADGE[channel] || "";
    }

    stateLabel(state) {
        return { open: _t("Open"), pending: _t("Pending"), resolved: _t("Resolved") }[state] || state;
    }

    stateClass(state) {
        return { open: "plain", pending: "warn", resolved: "ok" }[state] || "plain";
    }

    when(value) {
        if (!value) {
            return "";
        }
        const dt = deserializeDateTime(value);
        const now = DateTime.local();
        if (dt.hasSame(now, "day")) {
            return dt.toFormat("HH:mm");
        }
        if (dt.hasSame(now.minus({ days: 1 }), "day")) {
            return _t("Yesterday");
        }
        return dt.toFormat(dt.hasSame(now, "year") ? "d MMM" : "d MMM yyyy");
    }

    openRail(entry) {
        this.action.doAction(entry.action);
    }

    // ── Thread ───────────────────────────────────────────────────────────
    /** The messages with a line wherever the day changes. */
    get items() {
        const items = [];
        let day = "";
        for (const m of this.state.thread.messages) {
            const dt = deserializeDateTime(m.at);
            const label = this.dayLabel(dt);
            if (label !== day) {
                day = label;
                items.push({ key: "d" + m.key, day: label });
            }
            items.push({ key: m.key, m, time: dt.toFormat("HH:mm") });
        }
        return items;
    }

    dayLabel(dt) {
        const now = DateTime.local();
        if (dt.hasSame(now, "day")) {
            return _t("Today");
        }
        if (dt.hasSame(now.minus({ days: 1 }), "day")) {
            return _t("Yesterday");
        }
        return dt.toFormat("d MMM yyyy");
    }

    channelLabel(channel) {
        return CHANNEL[channel] || channel;
    }

    sender(m) {
        if (!m.out) {
            return this.state.thread.name;
        }
        return m.auto ? _t("Sent automatically") : _t("Contact Centre");
    }

    get waitingText() {
        const thread = this.state.thread;
        if (!thread || !thread.waiting || !thread.waiting_since) {
            return "";
        }
        const minutes = Math.max(1, Math.round(DateTime.local().diff(deserializeDateTime(thread.waiting_since)).as("minutes")));
        if (minutes < 60) {
            return minutes === 1 ? _t("Waiting 1 minute for a reply") : _t("Waiting %s minutes for a reply", minutes);
        }
        const hours = Math.round(minutes / 60);
        if (hours < 48) {
            return hours === 1 ? _t("Waiting 1 hour for a reply") : _t("Waiting %s hours for a reply", hours);
        }
        return _t("Waiting %s days for a reply", Math.round(hours / 24));
    }

    scrollToEnd() {
        const el = this.threadRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    async transcribe(m) {
        if (!m.wa_message_id || this.state.transcribing) {
            return;
        }
        this.state.transcribing = m.key;
        try {
            await this.orm.call("whatsapp.message", "action_transcribe", [[m.wa_message_id]]);
            await this.loadThread(this.state.sel);
        } finally {
            this.state.transcribing = false;
        }
    }

    // ── Reply box ────────────────────────────────────────────────────────
    /** Why a typed message cannot go on the chosen channel, or "". */
    get composerLock() {
        const thread = this.state.thread;
        if (this.state.channel === "whatsapp") {
            if (!thread.has_whatsapp) {
                return _t("This contact has no WhatsApp number.");
            }
            if (!thread.window_open) {
                return _t("WhatsApp only allows a typed message within 24 hours of their last one. Send a template, or switch to SMS.");
            }
        } else if (!thread.phone) {
            return _t("This contact has no phone number for an SMS.");
        }
        return "";
    }

    toggleChannel() {
        this.state.channel = this.state.channel === "whatsapp" ? "sms" : "whatsapp";
    }

    onText(ev) {
        this.state.text = ev.target.value;
    }

    onKey(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    growComposer() {
        const el = this.composerRef.el;
        if (el) {
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
        }
    }

    async send() {
        const text = this.state.text.trim();
        if (!text || this.state.sending || this.composerLock) {
            return;
        }
        this.state.sending = true;
        try {
            const sent = await this.orm.call(CONTACT, "action_send_reply", [[this.state.sel], this.state.channel, text]);
            if (sent) {
                this.state.text = "";
            } else {
                this.notification.add(_t("The message was not sent. The thread shows why."), { type: "warning" });
            }
            await this.reload();
        } finally {
            this.state.sending = false;
        }
    }

    insertReply() {
        this.state.text = this.state.thread.ai.reply;
        this.state.pane = "thread";
        if (this.composerRef.el) {
            this.composerRef.el.focus();
        }
    }

    // ── Templates ────────────────────────────────────────────────────────
    async toggleTemplates() {
        this.state.menu = this.state.menu === "template" ? null : "template";
        if (this.state.menu) {
            this.state.tpl.error = "";
            this.state.tpl.channel = this.state.channel;
            await this.loadTemplates();
        }
    }

    async loadTemplates() {
        const tpl = this.state.tpl;
        tpl.list = await this.orm.searchRead(
            "contact.centre.template", [["channel", "=", tpl.channel], ["active", "=", true]], ["name"], { order: "name" }
        );
        if (!tpl.list.some((t) => t.id === tpl.id)) {
            tpl.id = false;
        }
    }

    onTemplateChannel(ev) {
        this.state.tpl.channel = ev.target.value;
        this.state.tpl.error = "";
        this.loadTemplates();
    }

    onTemplate(ev) {
        this.state.tpl.id = parseInt(ev.target.value, 10) || false;
    }

    async sendTemplate() {
        const tpl = this.state.tpl;
        if (!tpl.id || tpl.sending) {
            return;
        }
        tpl.sending = true;
        tpl.error = "";
        try {
            const result = await this.orm.call(CONTACT, "action_send_template", [[this.state.sel], tpl.id]);
            if (result && result.error) {
                tpl.error = result.error;
            } else {
                this.state.menu = null;
                tpl.id = false;
                await this.reload();
            }
        } finally {
            tpl.sending = false;
        }
    }

    // ── Calls ────────────────────────────────────────────────────────────
    async toggleCallMenu() {
        this.state.menu = this.state.menu === "call" ? null : "call";
        if (this.state.menu && this.state.voiceBots === null) {
            try {
                this.state.voiceBots = await this.orm.searchRead(
                    "whatsapp.chatbot", [["channel", "=", "voice"], ["status", "=", "published"]], ["name"]
                );
            } catch {
                this.state.voiceBots = [];
            }
        }
    }

    /** WhatsApp call, with a script to follow when one is picked. The phone card runs both. */
    callWhatsApp(bot) {
        this.state.menu = null;
        const thread = this.state.thread;
        if (!thread.phone) {
            this.notification.add(_t("This contact has no phone number."), { type: "warning" });
            return;
        }
        if (!this.calling) {
            this.notification.add(_t("WhatsApp calling isn't available."), { type: "danger" });
            return;
        }
        this.calling.dialCall({
            toNumber: thread.phone,
            partnerId: thread.partner_id || undefined,
            partnerName: thread.name,
            chatbotId: bot ? bot.id : undefined,
            chatbotName: bot ? bot.name : undefined,
        });
    }

    callVoip() {
        const softphone = this.softphone;
        const thread = this.state.thread;
        if (!softphone || !thread.phone) {
            this.notification.add(_t("The softphone isn't ready, or this contact has no phone number."), { type: "warning" });
            return;
        }
        const status = softphone.state.status;
        if (["ringing", "calling", "incall"].includes(status)) {
            this.notification.add(_t("You're already on a call."), { type: "warning" });
            return;
        }
        if (status !== "registered") {
            // Opening the pad retries the connection and shows what's wrong.
            if (!softphone.state.dialerOpen) {
                softphone.toggleDialer();
            }
            this.notification.add(_t("The softphone isn't connected yet. Check the pad, then try again."), { type: "warning" });
            return;
        }
        softphone.dial(thread.phone);
    }

    get callTime() {
        const start = this.phone.call && this.phone.call.startTime;
        if (!start) {
            return _t("Connecting…");
        }
        const seconds = Math.max(0, Math.floor((this.state.now - start) / 1000));
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
    }

    callMute() {
        this.calling.card.mute();
    }

    callTransfer() {
        this.calling.card.openTransfer(this.phone.call.callLogId);
    }

    callEnd() {
        this.calling.card.hangup();
    }

    // ── Call script (the phone card's script, followed in the card here) ──
    scriptAnswer(text) {
        this.calling.card.scriptAnswer(text);
    }

    onScriptText(ev) {
        this.state.scriptText = ev.target.value;
    }

    scriptSubmit() {
        const text = this.state.scriptText.trim();
        if (text) {
            this.state.scriptText = "";
            this.scriptAnswer(text);
        }
    }

    scriptEnd() {
        this.calling.card.endScript();
    }

    // ── Information card ─────────────────────────────────────────────────
    showList() {
        this.state.pane = "list";
    }

    showThread() {
        this.state.pane = "thread";
    }

    /** On a phone the card is a pane of its own; on a wide screen it opens and closes. */
    toggleInfo() {
        if (this.env.isSmall) {
            this.state.infoOpen = true;
            this.state.pane = "info";
        } else {
            this.state.infoOpen = !this.state.infoOpen;
        }
    }

    setTab(key) {
        this.state.tab = key;
    }

    onScriptKey(ev) {
        if (ev.key === "Enter") {
            this.scriptSubmit();
        }
    }

    get tabs() {
        const tabs = [{ key: "conversation", label: _t("Conversation") }];
        if (this.phone.script) {
            tabs.unshift({ key: "script", label: _t("Call script") });
        }
        tabs.push({ key: "notes", label: _t("Notes") });
        return tabs;
    }

    get states() {
        return ["open", "pending", "resolved"].map((key) => ({ key, label: this.stateLabel(key) }));
    }

    async setState(state) {
        const thread = this.state.thread;
        if (thread.state === state) {
            return;
        }
        thread.state = state;
        await this.orm.call(WS, "ws_set_state", [thread.id, state]);
        await this.reload();
    }

    async onDisposition(ev) {
        const thread = this.state.thread;
        thread.disposition_id = parseInt(ev.target.value, 10) || false;
        await this.saveWrapUp();
    }

    onNote(ev) {
        this.state.thread.disposition_note = ev.target.value;
    }

    async saveWrapUp() {
        const thread = this.state.thread;
        await this.orm.call(CONTACT, "action_set_disposition", [[thread.id], thread.disposition_id, thread.disposition_note]);
    }

    sentimentClass(sentiment) {
        return { positive: "ok", neutral: "plain", negative: "warn" }[sentiment] || "plain";
    }

    sentimentLabel(sentiment) {
        return { positive: _t("Positive"), neutral: _t("Neutral"), negative: _t("Negative") }[sentiment] || sentiment;
    }

    /** One AI call, the same as the button on the contact's form. */
    async analyse() {
        if (this.state.analysing) {
            return;
        }
        this.state.analysing = true;
        try {
            const ai = await this.orm.call(WS, "ws_ai_refresh", [this.state.sel]);
            if (ai && this.state.thread) {
                this.state.thread.ai = ai;
            }
        } finally {
            this.state.analysing = false;
        }
    }

    get details() {
        return this.state.thread.details.filter((d) => d.value);
    }
}

registry.category("actions").add("contact_centre_workspace", ContactCentreWorkspace);
