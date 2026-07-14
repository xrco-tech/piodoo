/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class ContactCentreAiOps extends Component {
    static template = "contact_centre_ai_ops.AiOps";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loadingSessions: true,
            sessions: [],
            selectedSessionId: false,
            selectedSession: false,
            loadingMessages: false,
            messages: [],
            actions: [],
            composerText: "",
            sending: false,
            renamingSessionId: false,
            renameText: "",
        });

        this.composerRef = useRef("aiOpsComposer");
        useEffect(
            () => this._autoResizeComposer(),
            () => [this.state.composerText]
        );

        onWillStart(() => this.loadSessions());
    }

    // -------------------------------------------------------------------------
    // Data loading
    // -------------------------------------------------------------------------

    async loadSessions() {
        this.state.loadingSessions = true;
        try {
            this.state.sessions = await this.orm.searchRead(
                "contact.centre.ai.chat",
                [],
                ["name", "write_date"],
                { order: "write_date desc", limit: 100 }
            );
        } finally {
            this.state.loadingSessions = false;
        }
    }

    startRename(session, ev) {
        ev.stopPropagation();
        this.state.renamingSessionId = session.id;
        this.state.renameText = session.name;
    }

    onRenameInput(ev) {
        this.state.renameText = ev.target.value;
    }

    async saveRename(sessionId, ev) {
        ev.stopPropagation();
        const name = this.state.renameText.trim();
        this.state.renamingSessionId = false;
        if (!name) {
            return;
        }
        await this.orm.write("contact.centre.ai.chat", [sessionId], { name });
        await this.loadSessions();
        if (this.state.selectedSessionId === sessionId) {
            this.state.selectedSession = this.state.sessions.find((s) => s.id === sessionId) || false;
        }
    }

    cancelRename(ev) {
        ev.stopPropagation();
        this.state.renamingSessionId = false;
    }

    onRenameKeydown(sessionId, ev) {
        if (ev.key === "Enter") {
            this.saveRename(sessionId, ev);
        } else if (ev.key === "Escape") {
            this.cancelRename(ev);
        }
    }

    async createNewChat() {
        const id = await this.orm.create("contact.centre.ai.chat", [{ name: "New Chat" }]);
        await this.loadSessions();
        await this.selectSession(id[0]);
    }

    async selectSession(sessionId) {
        this.state.selectedSessionId = sessionId;
        this.state.selectedSession = this.state.sessions.find((s) => s.id === sessionId) || false;
        await Promise.all([this.loadMessages(sessionId), this.loadActions(sessionId)]);
    }

    async loadMessages(sessionId) {
        this.state.loadingMessages = true;
        try {
            this.state.messages = await this.orm.searchRead(
                "contact.centre.ai.chat.message",
                [["session_id", "=", sessionId]],
                ["role", "content"],
                { order: "create_date asc", limit: 500 }
            );
        } finally {
            this.state.loadingMessages = false;
        }
    }

    async loadActions(sessionId) {
        this.state.actions = await this.orm.searchRead(
            "contact.centre.ai.chat.action",
            [["session_id", "=", sessionId]],
            ["tool_name", "tool_input", "tool_result", "success"],
            { order: "create_date asc", limit: 200 }
        );
    }

    // Templates can't reference the global JSON object directly (Owl's
    // expression compiler resolves bare identifiers against the component
    // context, not window), so this wraps it for use in t-esc.
    formatToolJson(value) {
        return JSON.stringify(value, null, 2);
    }

    // -------------------------------------------------------------------------
    // Composer
    // -------------------------------------------------------------------------

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

    async sendMessage() {
        const text = this.state.composerText.trim();
        if (!text || !this.state.selectedSessionId || this.state.sending) {
            return;
        }
        this.state.composerText = "";
        this.state.sending = true;
        // Optimistic local echo — send_message() is a single round trip that
        // creates the user message AND generates the assistant reply, so
        // without this the user's own message wouldn't appear until the AI
        // finishes responding.
        this.state.messages = [...this.state.messages, { id: `local-${Date.now()}`, role: "user", content: text }];
        try {
            await this.orm.call("contact.centre.ai.chat", "send_message", [
                [this.state.selectedSessionId], text,
            ]);
        } catch (_e) {
            this.notification.add("The AI Copilot request failed.", { type: "danger" });
        } finally {
            this.state.sending = false;
            await Promise.all([
                this.loadMessages(this.state.selectedSessionId),
                this.loadActions(this.state.selectedSessionId),
                this.loadSessions(),
            ]);
        }
    }
}

registry.category("actions").add("contact_centre_ai_ops", ContactCentreAiOps);
