/** @odoo-module **/
// UCX inbox — Contact Centre skin, Gen-2 data.
// The skin is UCX's own (inbox_cc.scss, o_cx_inbox_cc_*): it was vendored from
// contact_centre_inbox so UCX carries no dependency on the Gen-1 inbox module.
// Binds to comm.conversation / comm.interaction and the UCX AI Copilot.
// The Gen-1-only bits (voice-script panel, call-picker) are intentionally left
// out — there's no Gen-2 equivalent yet.
import { Component, useState, useRef, useEffect, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chatter } from "@mail/chatter/web_portal/chatter";

const SENDABLE_CHANNELS = ["whatsapp", "sms", "email"];

export class CxInboxCc extends Component {
    static template = "cx_module.InboxCc";
    static components = { Chatter };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.busService = useService("bus_service");
        this.ui = useService("ui");

        this.state = useState({
            loadingList: true,
            conversations: [],
            stateFilter: false,
            searchQuery: "",
            selectedId: false,
            selected: false,
            loadingMessages: false,
            messages: [],
            composerText: "",
            composerChannel: "whatsapp",
            showLeftPane: true,
            showSide: false,
            transcribingId: false,
            showNotes: false,
            ai: {},
            aiLoading: false,
            dispositions: [],
            dispositionId: false,
            dispositionNote: "",
            showTemplatePicker: false,
            templateChannel: "whatsapp",
            templates: [],
            selectedTemplateId: false,
            templateSending: false,
            templateError: "",
        });

        this.threadRef = useRef("thread");
        useEffect(() => this._scrollThreadToBottom(), () => [this.state.messages]);

        this.debouncedLoad = useDebounced(() => this.loadConversations(), 300);
        this._onBus = this._onBus.bind(this);

        onWillStart(async () => {
            await Promise.all([this.loadConversations(), this.loadDispositions()]);
        });

        this.busService.addChannel("cx_inbox");
        this.busService.subscribe("cx_inbox_new_interaction", this._onBus);
        onWillDestroy(() => {
            this.busService.unsubscribe("cx_inbox_new_interaction", this._onBus);
            this.busService.deleteChannel("cx_inbox");
        });
    }

    // ── Data ────────────────────────────────────────────────────────────
    async loadConversations() {
        this.state.loadingList = true;
        let domain = this.state.stateFilter
            ? [["lifecycle_state", "=", this.state.stateFilter]]
            : [];
        const term = this.state.searchQuery.trim();
        if (term) {
            domain = domain.concat([["partner_id.name", "ilike", term]]);
        }
        try {
            this.state.conversations = await this.orm.searchRead(
                "comm.conversation",
                domain,
                ["name", "partner_id", "primary_channel_code", "lifecycle_state", "last_activity_at",
                 "partner_email", "partner_mobile", "partner_phone"],
                { order: "last_activity_at desc nulls last", limit: 200 }
            );
        } finally {
            this.state.loadingList = false;
        }
    }

    async selectConversation(id) {
        this.state.selectedId = id;
        this.state.selected = this.state.conversations.find((c) => c.id === id) || false;
        const code = this.state.selected && this.state.selected.primary_channel_code;
        this.state.composerChannel = SENDABLE_CHANNELS.includes(code) ? code : "whatsapp";
        this.state.showNotes = false;
        // On phones, collapse the list so the thread takes over (master-detail).
        if (this.ui.isSmall) {
            this.state.showLeftPane = false;
            this.state.showSide = false;
        }
        await Promise.all([this.loadMessages(id), this.loadCopilot(id)]);
    }

    async loadMessages(id) {
        this.state.loadingMessages = true;
        try {
            this.state.messages = await this.orm.searchRead(
                "comm.interaction",
                [["conversation_id", "=", id]],
                ["channel_code", "direction", "raw_body", "rendered_body", "status", "at", "recording_url", "recording_duration", "transcript", "source_model", "source_id"],
                { order: "at asc", limit: 500 }
            );
        } finally {
            this.state.loadingMessages = false;
        }
    }

    async loadDispositions() {
        this.state.dispositions = await this.orm.searchRead(
            "comm.disposition", [], ["name"], { order: "sequence, name" }
        );
    }

    async loadCopilot(id) {
        const recs = await this.orm.read(
            "comm.conversation", [id],
            ["ai_summary", "ai_sentiment", "ai_suggested_reply", "ai_analyzed_date",
             "disposition_id", "disposition_note"]
        );
        const rec = recs && recs.length ? recs[0] : {};
        this.state.ai = rec;
        this.state.dispositionId = rec.disposition_id ? rec.disposition_id[0] : false;
        this.state.dispositionNote = rec.disposition_note || "";
    }

    async onDispositionChange(ev) {
        if (!this.state.selectedId) {
            return;
        }
        const val = parseInt(ev.target.value, 10) || false;
        this.state.dispositionId = val;
        await this.orm.call("comm.conversation", "action_set_disposition", [
            [this.state.selectedId], val, this.state.dispositionNote,
        ]);
    }

    async saveDispositionNote() {
        if (!this.state.selectedId) {
            return;
        }
        await this.orm.call("comm.conversation", "action_set_disposition", [
            [this.state.selectedId], this.state.dispositionId, this.state.dispositionNote,
        ]);
    }

    // ── Send template ───────────────────────────────────────────────────
    async toggleTemplatePicker() {
        this.state.showTemplatePicker = !this.state.showTemplatePicker;
        this.state.templateError = "";
        if (this.state.showTemplatePicker) {
            await this.loadTemplates();
        }
    }

    async loadTemplates() {
        this.state.templates = await this.orm.searchRead(
            "contact.centre.template",
            [["channel", "=", this.state.templateChannel], ["active", "=", true]],
            ["name"], { order: "name" }
        );
        if (!this.state.templates.some((t) => t.id === this.state.selectedTemplateId)) {
            this.state.selectedTemplateId = false;
        }
    }

    onTemplateChannelChange(ev) {
        this.state.templateChannel = ev.target.value;
        this.state.selectedTemplateId = false;
        this.state.templateError = "";
        this.loadTemplates();
    }

    onTemplateSelect(ev) {
        this.state.selectedTemplateId = parseInt(ev.target.value, 10) || false;
    }

    get templateWarning() {
        const c = this.state.selected;
        if (!c) return "";
        const ch = this.state.templateChannel;
        if (ch === "email" && !c.partner_email) {
            return "This contact has no email address set — an email template can't be sent.";
        }
        if ((ch === "sms" || ch === "whatsapp") && !c.partner_mobile && !c.partner_phone) {
            return ch === "sms"
                ? "This contact has no phone number set — an SMS template can't be sent."
                : "This contact has no WhatsApp number set — a WhatsApp template can't be sent.";
        }
        return "";
    }

    async sendTemplate() {
        if (!this.state.selectedTemplateId || this.templateWarning || this.state.templateSending) {
            return;
        }
        this.state.templateSending = true;
        this.state.templateError = "";
        try {
            const res = await this.orm.call("comm.conversation", "action_send_template", [
                [this.state.selectedId], this.state.selectedTemplateId,
            ]);
            if (res && res.error) {
                this.state.templateError = res.error;
            } else {
                this.state.showTemplatePicker = false;
                this.state.selectedTemplateId = false;
                await this.loadMessages(this.state.selectedId);
            }
        } finally {
            this.state.templateSending = false;
        }
    }

    onDispositionNoteInput(ev) {
        this.state.dispositionNote = ev.target.value;
    }

    async generateCopilot() {
        if (!this.state.selectedId || this.state.aiLoading) {
            return;
        }
        this.state.aiLoading = true;
        try {
            await this.orm.call("comm.conversation", "action_cx_generate_copilot", [
                [this.state.selectedId],
            ]);
            await this.loadCopilot(this.state.selectedId);
        } finally {
            this.state.aiLoading = false;
        }
    }

    insertSuggestedReply() {
        if (this.state.ai && this.state.ai.ai_suggested_reply) {
            this.state.composerText = this.state.ai.ai_suggested_reply;
        }
    }

    // ── UI actions ──────────────────────────────────────────────────────
    filterByState(value) {
        this.state.stateFilter = this.state.stateFilter === value ? false : value;
        this.loadConversations();
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        this.debouncedLoad();
    }

    onComposerInput(ev) {
        this.state.composerText = ev.target.value;
    }

    toggleLeftPane() {
        this.state.showLeftPane = !this.state.showLeftPane;
    }

    toggleSide() {
        this.state.showSide = !this.state.showSide;
    }

    // Manually transcribe a WhatsApp voice note now (same Whisper + Claude
    // pipeline as the cron), rather than waiting for the 2-minute cron.
    async transcribeMessage(message) {
        if (!message.source_id || this.state.transcribingId) {
            return;
        }
        this.state.transcribingId = message.id;
        try {
            await this.orm.call("whatsapp.message", "action_transcribe", [[message.source_id]]);
            await this.loadMessages(this.state.selectedId);
        } finally {
            this.state.transcribingId = false;
        }
    }

    toggleNotes() {
        this.state.showNotes = !this.state.showNotes;
    }

    _scrollThreadToBottom() {
        const el = this.threadRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    async sendReply() {
        const text = this.state.composerText.trim();
        if (!text || !this.state.selectedId) {
            return;
        }
        this.state.composerText = "";
        await this.orm.call("comm.conversation", "action_cx_send_reply", [
            [this.state.selectedId], this.state.composerChannel, text,
        ]);
        await this.loadMessages(this.state.selectedId);
    }

    // ── Real-time ───────────────────────────────────────────────────────
    _onBus(payload) {
        this.loadConversations();
        if (payload && payload.conversation_id === this.state.selectedId) {
            this.loadMessages(this.state.selectedId);
        }
    }
}

registry.category("actions").add("cx_module_inbox_cc", CxInboxCc);
