/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chatter } from "@mail/chatter/web_portal/chatter";

// Channels an agent can type a reply on (must match CX_SENDABLE_CHANNELS server-side).
const SENDABLE_CHANNELS = ["whatsapp", "sms", "email"];

export class CxInbox extends Component {
    static template = "cx_module.Inbox";
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
            dispositions: [],
            dispositionId: false,
            dispositionNote: "",
        });

        this.threadRef = useRef("thread");
        // Re-scroll to the newest message whenever the array reference changes:
        // selecting a conversation, sending a reply, or a bus-driven reload.
        useEffect(
            () => this._scrollThreadToBottom(),
            () => [this.state.messages]
        );

        this.debouncedLoad = useDebounced(() => this.loadConversations(), 300);
        this._onBus = this._onBus.bind(this);

        onWillStart(async () => {
            await Promise.all([this.loadConversations(), this.loadDispositions()]);
        });

        // Live updates: the server _sendone's to the "cx_inbox" channel on every
        // new comm.interaction (see cx_conversation.py).
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
        await Promise.all([this.loadMessages(id), this.loadDisposition(id)]);
    }

    async loadDispositions() {
        this.state.dispositions = await this.orm.searchRead(
            "comm.disposition", [], ["name"], { order: "sequence, name" }
        );
    }

    async loadDisposition(id) {
        const recs = await this.orm.read(
            "comm.conversation", [id], ["disposition_id", "disposition_note"]
        );
        const rec = recs && recs.length ? recs[0] : {};
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

    onDispositionNoteInput(ev) {
        this.state.dispositionNote = ev.target.value;
    }

    async saveDispositionNote() {
        if (!this.state.selectedId) {
            return;
        }
        await this.orm.call("comm.conversation", "action_set_disposition", [
            [this.state.selectedId], this.state.dispositionId, this.state.dispositionNote,
        ]);
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

registry.category("actions").add("cx_module_inbox", CxInbox);
