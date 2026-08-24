/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { VoiceScriptPanel } from "./voice_script_panel";

const SENDABLE_CHANNELS = ["whatsapp", "sms"];

export class ContactCentreInbox extends Component {
    static template = "contact_centre_inbox.Inbox";
    static components = { Chatter, VoiceScriptPanel };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.ui = useService("ui");

        // Set when opened via a campaign's "Open Workspace" smart button
        // (contact.centre.campaign.action_open_workspace) - plain instance
        // fields, not state, since they're fixed for the lifetime of this
        // component instance and never change after mount.
        this.campaignId = this.props.action.params?.campaign_id || false;
        this.campaignName = this.props.action.params?.campaign_name || "";

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
            showSide: false,
            showInternalNotes: false,
            aiAvailable: false,
            ai: { ai_summary: "", ai_sentiment: false, ai_suggested_reply: "", ai_analyzed_date: false },
            showCallPicker: false,
            voiceChatbots: [],
            showVoiceScript: false,
            voiceSessionId: false,
            voiceChatbotName: "",
            rightPaneTab: "copilot",
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

        this.composerRef = useRef("composerTextarea");
        // Auto-grow the composer textarea to fit its content (capped by
        // max-height/overflow in CSS) - re-run on every change to the text,
        // regardless of whether it came from typing, "Insert as Reply", or
        // being cleared after sending.
        useEffect(
            () => this._autoResizeComposer(),
            () => [this.state.composerText]
        );

        this.threadRef = useRef("thread");
        // Runs whenever state.messages gets a new array reference - covers
        // selecting a conversation, sending a reply, and a new inbound
        // message arriving over the bus, all in one place.
        useEffect(
            () => this._scrollThreadToBottom(),
            () => [this.state.messages]
        );

        this._onBusNotification = this._onBusNotification.bind(this);
        this.debouncedLoadContacts = useDebounced(() => this.loadContacts(), 300);

        onWillStart(async () => {
            await Promise.all([this.loadContacts(), this.loadDispositions()]);
        });

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
        if (this.campaignId) {
            domain = domain.concat([["campaign_ids", "in", [this.campaignId]]]);
        }
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
                ["name", "phone_number", "email", "bsuid", "state", "last_contact_date", "partner_id"],
                // "nulls last" matters here: Postgres defaults DESC sorts to
                // NULLS FIRST, so without it every contact with zero message/
                // call history would rank above ones with real recent
                // engagement, not below.
                { order: "last_contact_date desc nulls last", limit: 200 }
            );
        } finally {
            this.state.loadingContacts = false;
        }
    }

    async selectContact(contactId) {
        this.state.selectedContactId = contactId;
        this.state.selectedContact = this.state.contacts.find((c) => c.id === contactId) || false;
        // On phones, collapse the list so the thread takes over (master-detail).
        if (this.ui.isSmall) {
            this.state.showLeftPane = false;
            this.state.showSide = false;
        }
        await Promise.all([
            this.loadMessages(contactId),
            this.loadAiPanel(contactId),
            this.loadDisposition(contactId),
        ]);
    }

    async loadDispositions() {
        this.state.dispositions = await this.orm.searchRead(
            "comm.disposition", [], ["name"], { order: "sequence, name" }
        );
    }

    async loadDisposition(contactId) {
        const [rec] = await this.orm.read(
            "contact.centre.contact", [contactId], ["disposition_id", "disposition_note"]
        );
        this.state.dispositionId = rec && rec.disposition_id ? rec.disposition_id[0] : false;
        this.state.dispositionNote = (rec && rec.disposition_note) || "";
    }

    async onDispositionChange(ev) {
        if (!this.state.selectedContactId) {
            return;
        }
        const val = parseInt(ev.target.value, 10) || false;
        this.state.dispositionId = val;
        await this.orm.call("contact.centre.contact", "action_set_disposition", [
            [this.state.selectedContactId], val, this.state.dispositionNote,
        ]);
    }

    onDispositionNoteInput(ev) {
        this.state.dispositionNote = ev.target.value;
    }

    async saveDispositionNote() {
        if (!this.state.selectedContactId) {
            return;
        }
        await this.orm.call("contact.centre.contact", "action_set_disposition", [
            [this.state.selectedContactId], this.state.dispositionId, this.state.dispositionNote,
        ]);
    }

    // ── Send template ───────────────────────────────────────────────────
    async toggleTemplatePicker() {
        this.state.showTemplatePicker = !this.state.showTemplatePicker;
        this.state.templateError = "";
        if (this.state.showTemplatePicker) {
            this.state.showCallPicker = false;
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

    // Client-side pre-send validation: warn (and block) when the contact
    // has no address for the chosen channel.
    get templateWarning() {
        const c = this.state.selectedContact;
        if (!c) return "";
        const ch = this.state.templateChannel;
        if (ch === "email" && !c.email) {
            return "This contact has no email address set — an email template can't be sent.";
        }
        if (ch === "sms" && !c.phone_number) {
            return "This contact has no phone number set — an SMS template can't be sent.";
        }
        if (ch === "whatsapp" && !c.phone_number && !c.bsuid) {
            return "This contact has no WhatsApp number set — a WhatsApp template can't be sent.";
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
            const res = await this.orm.call("contact.centre.contact", "action_send_template", [
                [this.state.selectedContactId], this.state.selectedTemplateId,
            ]);
            if (res && res.error) {
                this.state.templateError = res.error;
            } else {
                this.state.showTemplatePicker = false;
                this.state.selectedTemplateId = false;
                await this.loadMessages(this.state.selectedContactId);
            }
        } finally {
            this.state.templateSending = false;
        }
    }

    async loadMessages(contactId) {
        this.state.loadingMessages = true;
        try {
            this.state.messages = await this.orm.searchRead(
                "contact.centre.message",
                [["contact_id", "=", contactId]],
                ["channel", "direction", "body_text", "status", "message_timestamp", "message_type",
                 "call_recording_id", "call_recording_url", "call_recording_duration",
                 "call_disposition_id", "call_disposition_note"],
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

    onComposerInput(ev) {
        this.state.composerText = ev.target.value;
    }

    _autoResizeComposer() {
        const el = this.composerRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
    }

    _scrollThreadToBottom() {
        const el = this.threadRef.el;
        if (!el) {
            return;
        }
        el.scrollTop = el.scrollHeight;
    }

    insertSuggestedReply() {
        if (this.state.ai.ai_suggested_reply) {
            this.state.composerText = this.state.ai.ai_suggested_reply;
        }
    }

    toggleLeftPane() {
        this.state.showLeftPane = !this.state.showLeftPane;
    }

    toggleSide() {
        this.state.showSide = !this.state.showSide;
    }

    async toggleCallPicker() {
        this.state.showCallPicker = !this.state.showCallPicker;
        if (this.state.showCallPicker && !this.state.voiceChatbots.length) {
            this.state.voiceChatbots = await this.orm.searchRead(
                "whatsapp.chatbot",
                [["channel", "=", "voice"], ["status", "=", "published"]],
                ["name"]
            );
        }
    }

    async startVoiceCall(chatbotId) {
        this.state.showCallPicker = false;
        const contact = this.state.selectedContact;
        if (!contact || !contact.phone_number) {
            this.notification.add("This contact has no phone number.", { type: "warning" });
            return;
        }
        const callingService = this.env.services.comm_whatsapp_calling;
        if (!callingService) {
            this.notification.add("WhatsApp calling isn't available.", { type: "danger" });
            return;
        }

        let sessionId = false;
        if (chatbotId) {
            try {
                const startData = await rpc("/voice/start", {
                    chatbot_id: chatbotId,
                    contact_details: { name: contact.name, mobile: contact.phone_number },
                });
                sessionId = startData.session_id;
            } catch (_e) {
                this.notification.add("Failed to start the voice script — calling without one.", { type: "warning" });
            }
        }

        callingService.dialCall({
            toNumber: contact.phone_number,
            partnerId: contact.partner_id ? contact.partner_id[0] : undefined,
            partnerName: contact.name,
            chatbotId: chatbotId || undefined,
        });

        if (sessionId) {
            const chatbot = this.state.voiceChatbots.find((c) => c.id === chatbotId);
            this.state.voiceSessionId = sessionId;
            this.state.voiceChatbotName = chatbot ? chatbot.name : "";
            this.state.showVoiceScript = true;
            this.state.rightPaneTab = "script";
            // On phones the right pane is an off-canvas drawer — slide it in so
            // the agent can follow the script.
            if (this.ui.isSmall) {
                this.state.showSide = true;
            }
        }
    }

    switchRightPaneTab(tab) {
        this.state.rightPaneTab = tab;
    }

    endVoiceScript() {
        this.state.showVoiceScript = false;
        this.state.voiceSessionId = false;
        this.state.voiceChatbotName = "";
        this.state.rightPaneTab = "copilot";
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
