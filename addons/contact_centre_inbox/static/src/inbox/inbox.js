/** @odoo-module **/

import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chatter } from "@mail/chatter/web_portal/chatter";

const SENDABLE_CHANNELS = ["whatsapp", "sms"];

export class ContactCentreInbox extends Component {
    static template = "contact_centre_inbox.Inbox";
    static components = { Chatter };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.busService = useService("bus_service");

        this.state = useState({
            loadingContacts: true,
            contacts: [],
            stateFilter: false,
            searchQuery: "",
            selectedContactId: false,
            selectedContact: false,
            loadingMessages: false,
            messages: [],
            composerText: "",
            composerChannel: "whatsapp",
            showLeftPane: true,
            showInternalNotes: false,
            aiAvailable: false,
            ai: { ai_summary: "", ai_sentiment: false, ai_suggested_reply: "", ai_analyzed_date: false },
        });

        this._onBusNotification = this._onBusNotification.bind(this);
        this.debouncedLoadContacts = useDebounced(() => this.loadContacts(), 300);

        onWillStart(() => this.loadContacts());

        this.busService.subscribe("contact_centre_new_message", this._onBusNotification);
        this.busService.start();
        onWillDestroy(() => {
            this.busService.unsubscribe("contact_centre_new_message", this._onBusNotification);
        });
    }

    // -------------------------------------------------------------------------
    // Data loading
    // -------------------------------------------------------------------------

    async loadContacts() {
        this.state.loadingContacts = true;
        let domain = this.state.stateFilter ? [["state", "=", this.state.stateFilter]] : [];
        const term = this.state.searchQuery.trim();
        if (term) {
            domain = domain.concat([
                "|", "|",
                ["name", "ilike", term],
                ["phone_number", "ilike", term],
                ["email", "ilike", term],
            ]);
        }
        try {
            this.state.contacts = await this.orm.searchRead(
                "contact.centre.contact",
                domain,
                ["name", "phone_number", "state", "last_contact_date"],
                { order: "last_contact_date desc", limit: 200 }
            );
        } finally {
            this.state.loadingContacts = false;
        }
    }

    async selectContact(contactId) {
        this.state.selectedContactId = contactId;
        this.state.selectedContact = this.state.contacts.find((c) => c.id === contactId) || false;
        await Promise.all([this.loadMessages(contactId), this.loadAiPanel(contactId)]);
    }

    async loadMessages(contactId) {
        this.state.loadingMessages = true;
        try {
            this.state.messages = await this.orm.searchRead(
                "contact.centre.message",
                [["contact_id", "=", contactId]],
                ["channel", "direction", "body_text", "status", "message_timestamp", "message_type"],
                { order: "message_timestamp asc", limit: 200 }
            );
            const lastSendable = [...this.state.messages].reverse().find(
                (m) => SENDABLE_CHANNELS.includes(m.channel)
            );
            if (lastSendable) {
                this.state.composerChannel = lastSendable.channel;
            }
        } finally {
            this.state.loadingMessages = false;
        }
    }

    async loadAiPanel(contactId) {
        try {
            const [record] = await this.orm.read("contact.centre.contact", [contactId], [
                "ai_summary", "ai_sentiment", "ai_suggested_reply", "ai_analyzed_date",
            ]);
            this.state.ai = record;
            this.state.aiAvailable = true;
        } catch (_e) {
            // contact_centre_ai_copilot isn't installed — hide the panel
            this.state.aiAvailable = false;
        }
    }

    // -------------------------------------------------------------------------
    // Actions
    // -------------------------------------------------------------------------

    filterByState(stateValue) {
        this.state.stateFilter = this.state.stateFilter === stateValue ? false : stateValue;
        this.loadContacts();
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        this.debouncedLoadContacts();
    }

    insertSuggestedReply() {
        if (this.state.ai.ai_suggested_reply) {
            this.state.composerText = this.state.ai.ai_suggested_reply;
        }
    }

    toggleLeftPane() {
        this.state.showLeftPane = !this.state.showLeftPane;
    }

    toggleInternalNotes() {
        this.state.showInternalNotes = !this.state.showInternalNotes;
        // Notes get cropped with all 3 panes open - free up the width by
        // hiding the conversation list while notes are shown, and restore
        // it when notes are hidden again.
        this.state.showLeftPane = !this.state.showInternalNotes;
    }

    async sendReply() {
        const text = this.state.composerText.trim();
        if (!text || !this.state.selectedContactId) {
            return;
        }
        this.state.composerText = "";
        await this.orm.call("contact.centre.contact", "action_send_reply", [
            [this.state.selectedContactId], this.state.composerChannel, text,
        ]);
        await this.loadMessages(this.state.selectedContactId);
    }

    // -------------------------------------------------------------------------
    // Real-time updates
    // -------------------------------------------------------------------------

    _onBusNotification(payload) {
        this.loadContacts();
        if (payload?.contact_id === this.state.selectedContactId) {
            this.loadMessages(this.state.selectedContactId);
        }
    }
}

registry.category("actions").add("contact_centre_inbox", ContactCentreInbox);
