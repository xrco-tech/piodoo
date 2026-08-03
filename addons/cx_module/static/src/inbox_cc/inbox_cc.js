/** @odoo-module **/
// UCX inbox — Contact Centre skin, Gen-2 data.
// Reuses contact_centre_inbox's o_cc_inbox_* skin (loaded via the module dep)
// but binds to comm.conversation / comm.interaction and the UCX AI Copilot.
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
            showNotes: false,
            ai: {},
            aiLoading: false,
        });

        this.threadRef = useRef("thread");
        useEffect(() => this._scrollThreadToBottom(), () => [this.state.messages]);

        this.debouncedLoad = useDebounced(() => this.loadConversations(), 300);
        this._onBus = this._onBus.bind(this);

        onWillStart(() => this.loadConversations());

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
                ["name", "partner_id", "primary_channel_code", "lifecycle_state", "last_activity_at"],
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
        await Promise.all([this.loadMessages(id), this.loadCopilot(id)]);
    }

    async loadMessages(id) {
        this.state.loadingMessages = true;
        try {
            this.state.messages = await this.orm.searchRead(
                "comm.interaction",
                [["conversation_id", "=", id]],
                ["channel_code", "direction", "raw_body", "rendered_body", "status", "at"],
                { order: "at asc", limit: 500 }
            );
        } finally {
            this.state.loadingMessages = false;
        }
    }

    async loadCopilot(id) {
        const recs = await this.orm.read(
            "comm.conversation", [id],
            ["ai_summary", "ai_sentiment", "ai_suggested_reply", "ai_analyzed_date"]
        );
        this.state.ai = recs && recs.length ? recs[0] : {};
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
