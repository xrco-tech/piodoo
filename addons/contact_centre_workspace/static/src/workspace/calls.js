/** @odoo-module **/

import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { when, dialWhatsApp, dialVoip } from "./util";

const WS = "contact.centre.workspace";
const PAGE = 40;

/** The Calls section: WhatsApp and VoIP calls in one list, one call beside it. */
export class ContactCentreCalls extends Component {
    static template = "contact_centre_workspace.Calls";
    static props = {
        boot: Object,
        callKey: { type: [String, Boolean], optional: true },
        setPane: Function,
        openConversation: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.bus = useService("bus_service");
        this.state = useState({
            pill: "all",
            search: "",
            rows: [],
            more: false,
            loading: true,
            sel: false,
            call: null,
            loadingCall: false,
            infoOpen: true,
            transcribing: false,
        });
        this.when = when;
        this.searchLater = useDebounced(() => this.loadAndLand(), 300);
        // A call that ends is copied into its conversation: that is the cue to refresh.
        this.refresh = useDebounced(() => this.reload(), 600);
        this.bus.subscribe("contact_centre_new_message", this.refresh);
        onWillDestroy(() => this.bus.unsubscribe("contact_centre_new_message", this.refresh));

        onWillStart(async () => {
            // A call it was asked to open stays open; otherwise it lands on the first one.
            this.pinned = this.state.sel = this.props.callKey || false;
            await this.loadAndLand();
            if (this.props.callKey) {
                await this.open(this.props.callKey);
            }
        });
    }

    // ── Loading ──────────────────────────────────────────────────────────
    async loadList(limit = PAGE) {
        this.state.loading = true;
        try {
            const result = await this.orm.call(WS, "ws_calls", [], {
                pill: this.state.pill, search: this.state.search, offset: 0, limit,
            });
            this.state.rows = result.rows;
            this.state.more = result.more;
        } finally {
            this.state.loading = false;
        }
    }

    async loadMore() {
        const result = await this.orm.call(WS, "ws_calls", [], {
            pill: this.state.pill, search: this.state.search, offset: this.state.rows.length, limit: PAGE,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async loadCall(key) {
        const call = await this.orm.call(WS, "ws_call", [key]);
        if (this.state.sel === key) {
            this.state.call = call;
        }
    }

    /** Nothing open, or what was open is not in the list any more: show the
     *  first row. A phone stays on the list. */
    async land() {
        const ids = this.state.rows.map((row) => row.key);
        if (this.typing || ids.includes(this.state.sel) || (this.state.sel && this.state.sel === this.pinned)) {
            return;
        }
        if (ids.length) {
            await this.open(ids[0], true);
        } else {
            this.state.sel = false;
            this.state.call = null;
        }
    }

    async loadAndLand() {
        await this.loadList();
        await this.land();
    }

    async reload() {
        await this.loadList(Math.max(PAGE, this.state.rows.length));
        // Not while a note is being typed: the reload would wipe it.
        if (this.state.sel && !this.typing) {
            await this.loadCall(this.state.sel);
        }
    }

    async open(key, stay = false) {
        this.state.sel = key;
        this.typing = false;
        if (!stay) {
            this.props.setPane("thread");
        }
        this.state.loadingCall = !this.state.call;
        try {
            await this.loadCall(key);
        } finally {
            this.state.loadingCall = false;
        }
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        return [
            { key: "all", label: _t("All") },
            { key: "missed", label: _t("Missed") },
            { key: "incoming", label: _t("Incoming") },
            { key: "outgoing", label: _t("Outgoing") },
            { key: "whatsapp", label: "WhatsApp" },
            { key: "voip", label: "VoIP" },
            { key: "no_outcome", label: _t("No outcome") },
        ];
    }

    setPill(key) {
        this.state.pill = key;
        this.loadAndLand();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchLater();
    }

    badge(line) {
        return line === "whatsapp" ? "WA" : "Tel";
    }

    /** "Missed", "Answered · 3:12". */
    summary(row) {
        return row.duration ? `${row.status} · ${row.duration}` : row.status;
    }

    // ── One call ─────────────────────────────────────────────────────────
    get title() {
        const call = this.state.call;
        const line = call.line === "whatsapp" ? "WhatsApp" : "VoIP";
        return call.incoming ? _t("Incoming %s call", line) : _t("Outgoing %s call", line);
    }

    full(value) {
        return value ? deserializeDateTime(value).toFormat("d MMM yyyy, HH:mm") : "";
    }

    kindClass(kind) {
        return { missed: "warn", answered: "ok" }[kind] || "plain";
    }

    sentimentClass(sentiment) {
        return { positive: "ok", neutral: "plain", negative: "warn" }[sentiment] || "plain";
    }

    sentimentLabel(sentiment) {
        return { positive: _t("Positive"), neutral: _t("Neutral"), negative: _t("Negative") }[sentiment] || sentiment;
    }

    get details() {
        return this.state.call.details
            .filter((d) => d.value)
            .map((d) => ({ label: d.label, value: d.time ? this.full(d.value) : d.value }));
    }

    /** The outcome the AI suggested, when it is one of ours and not already set. */
    get suggested() {
        const call = this.state.call;
        const name = ((call.ai && call.ai.suggested) || "").trim().toLowerCase();
        if (!name || !call.has_outcome) {
            return null;
        }
        const match = this.props.boot.dispositions.find((d) => d.name.trim().toLowerCase() === name);
        return match && match.id !== call.disposition_id ? match : null;
    }

    async transcribe() {
        if (this.state.transcribing) {
            return;
        }
        const key = this.state.sel;
        this.state.transcribing = true;
        try {
            const call = await this.orm.call(WS, "ws_call_transcribe", [key]);
            if (call && this.state.sel === key) {
                this.state.call = call;
            }
        } finally {
            this.state.transcribing = false;
        }
    }

    // ── Calling back ─────────────────────────────────────────────────────
    callWhatsApp() {
        const call = this.state.call;
        dialWhatsApp(this.env.services, { phone: call.number, name: call.name, partnerId: call.partner_id });
    }

    callVoip() {
        dialVoip(this.env.services, this.state.call.number);
    }

    // ── Outcome ──────────────────────────────────────────────────────────
    async saveOutcome() {
        const call = this.state.call;
        this.typing = false;
        await this.orm.call(WS, "ws_call_outcome", [call.key, call.disposition_id, call.note]);
        const row = this.state.rows.find((r) => r.key === call.key);
        if (row && call.has_outcome) {
            const disposition = this.props.boot.dispositions.find((d) => d.id === call.disposition_id);
            row.disposition = disposition ? disposition.name : "";
        }
    }

    onDisposition(ev) {
        this.state.call.disposition_id = parseInt(ev.target.value, 10) || false;
        this.saveOutcome();
    }

    useSuggested() {
        this.state.call.disposition_id = this.suggested.id;
        this.saveOutcome();
    }

    onNote(ev) {
        this.typing = true;
        this.state.call.note = ev.target.value;
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    showCall() {
        this.props.setPane("thread");
    }

    /** On a phone the card is a pane of its own; on a wide screen it opens and closes. */
    toggleInfo() {
        if (this.env.isSmall) {
            this.state.infoOpen = true;
            this.props.setPane("info");
        } else {
            this.state.infoOpen = !this.state.infoOpen;
        }
    }

    openConversation() {
        this.props.openConversation(this.state.call.contact_id);
    }
}
