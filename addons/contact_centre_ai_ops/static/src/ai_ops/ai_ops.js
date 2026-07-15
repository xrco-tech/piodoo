/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// ── Markdown → HTML ──────────────────────────────────────────────────────
// Minimal renderer for the AI's own replies (headings, bold/italic, inline
// and fenced code, and numbered/bulleted lists) - covers what the model
// actually produces without pulling in a markdown library. Escapes first
// so the model's own text can never inject markup.
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function renderInlineMarkdown(text) {
    let s = text;
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
    return s;
}

function renderMarkdownBlock(block) {
    const lines = block.split("\n");
    const headerMatch = lines.length === 1 && block.match(/^(#{1,6})\s+(.*)$/);
    if (headerMatch) {
        const level = Math.min(headerMatch[1].length + 2, 6); // keep headings small inside a chat bubble
        return `<h${level}>${renderInlineMarkdown(headerMatch[2])}</h${level}>`;
    }
    if (lines.every((l) => /^\s*\d+\.\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^\s*\d+\.\s+/, ""))}</li>`).join("");
        return `<ol>${items}</ol>`;
    }
    if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^\s*[-*]\s+/, ""))}</li>`).join("");
        return `<ul>${items}</ul>`;
    }
    return `<p>${lines.map(renderInlineMarkdown).join("<br>")}</p>`;
}

function markdownToHtml(text) {
    if (!text) {
        return "";
    }
    const escaped = escapeHtml(text);
    // Pull fenced code blocks out first so their contents skip inline
    // formatting and blank-line splitting, then splice back in at the end.
    const codeBlocks = [];
    const withPlaceholders = escaped.replace(/```(?:\w+)?\n?([\s\S]*?)```/g, (_match, code) => {
        const index = codeBlocks.length;
        codeBlocks.push(`<pre class="o_cc_aiops_md_code"><code>${code.replace(/\n$/, "")}</code></pre>`);
        return ` CODEBLOCK${index} `;
    });
    const html = withPlaceholders
        .split(/\n{2,}/)
        .map(renderMarkdownBlock)
        .join("")
        .replace(/ CODEBLOCK(\d+) /g, (_match, i) => codeBlocks[Number(i)]);
    return html;
}

// Maps a create/update tool's name to the model + result key holding the
// touched record's id, so the Actions Taken panel can offer a "View record"
// link. Deliberately excludes delete_dashboard_card (nothing left to view)
// and create_contacts_from_partners (returns multiple contacts, not one).
const ACTION_RECORD_MAP = {
    create_campaign: { model: "contact.centre.campaign", key: "campaign_id" },
    update_campaign: { model: "contact.centre.campaign", key: "campaign_id" },
    create_contact: { model: "contact.centre.contact", key: "contact_id" },
    update_contact: { model: "contact.centre.contact", key: "contact_id" },
    create_template: { model: "contact.centre.template", key: "template_id" },
    update_template: { model: "contact.centre.template", key: "template_id" },
    create_whatsapp_template: { model: "whatsapp.template", key: "template_id" },
    update_whatsapp_template: { model: "whatsapp.template", key: "template_id" },
    create_call_team: { model: "whatsapp.call.team", key: "team_id" },
    update_call_team: { model: "whatsapp.call.team", key: "team_id" },
    create_call_routing_rule: { model: "whatsapp.call.routing.rule", key: "rule_id" },
    update_call_routing_rule: { model: "whatsapp.call.routing.rule", key: "rule_id" },
    create_chatbot_flow: { model: "whatsapp.chatbot", key: "chatbot_id" },
    update_chatbot_flow: { model: "whatsapp.chatbot", key: "chatbot_id" },
    create_dashboard_card: { model: "contact.centre.dashboard.card", key: "card_id" },
    update_dashboard_card: { model: "contact.centre.dashboard.card", key: "card_id" },
};

export class ContactCentreAiOps extends Component {
    static template = "contact_centre_ai_ops.AiOps";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

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
            leftCollapsed: false,
            rightCollapsed: false,
        });

        this.composerRef = useRef("aiOpsComposer");
        useEffect(
            () => this._autoResizeComposer(),
            () => [this.state.composerText]
        );

        this.threadRef = useRef("aiOpsThread");
        useEffect(
            () => this._scrollThreadToBottom(),
            () => [this.state.messages]
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

    toggleLeftPane() {
        this.state.leftCollapsed = !this.state.leftCollapsed;
    }

    toggleRightPane() {
        this.state.rightCollapsed = !this.state.rightCollapsed;
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
                ["role", "content", "suggestions"],
                { order: "create_date asc", limit: 500 }
            );
        } finally {
            this.state.loadingMessages = false;
        }
    }

    async loadActions(sessionId) {
        const rows = await this.orm.searchRead(
            "contact.centre.ai.chat.action",
            [["session_id", "=", sessionId]],
            ["tool_name", "tool_input", "tool_result", "success"],
            { order: "create_date asc", limit: 200 }
        );
        // expanded is client-only UI state, not a real field - collapsed
        // by default so the list scans as just tool names + status.
        this.state.actions = rows.map((row) => ({ ...row, expanded: false }));
    }

    toggleAction(action) {
        action.expanded = !action.expanded;
    }

    // null when this action isn't a mapped create/update, failed, or the
    // expected id key is missing from tool_result - t-if in the template
    // just checks truthiness, so returning null cleanly hides the link.
    getActionRecordTarget(action) {
        if (!action.success) {
            return null;
        }
        const mapping = ACTION_RECORD_MAP[action.tool_name];
        if (!mapping) {
            return null;
        }
        const resId = action.tool_result && action.tool_result[mapping.key];
        if (typeof resId !== "number") {
            return null;
        }
        return { model: mapping.model, resId };
    }

    async openActionRecord(action, ev) {
        ev.stopPropagation(); // don't also trigger the row's collapse/expand toggle
        const target = this.getActionRecordTarget(action);
        if (!target) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: target.model,
            res_id: target.resId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    // Templates can't reference the global JSON object directly (Owl's
    // expression compiler resolves bare identifiers against the component
    // context, not window), so this wraps it for use in t-esc.
    formatToolJson(value) {
        return JSON.stringify(value, null, 2);
    }

    // markup() tells Owl's t-out to render this as HTML rather than
    // escaping it - safe here because markdownToHtml() escapes the raw
    // text before adding any tags.
    renderMarkdown(text) {
        return markup(markdownToHtml(text));
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

    // Runs whenever state.messages gets a new array reference - covers
    // selecting a chat, sending a message (optimistic echo), and the
    // AI's reply landing, all in one place.
    _scrollThreadToBottom() {
        const el = this.threadRef.el;
        if (!el) {
            return;
        }
        el.scrollTop = el.scrollHeight;
    }

    // Quick-reply chips for the AI's most recent message, when it ended
    // its turn with a <<suggestions>>[...]<<end>> tag (parsed server-side
    // into the suggestions field). Empty once the user's own message
    // becomes the latest one, so chips naturally disappear after use.
    get lastAssistantSuggestions() {
        const messages = this.state.messages;
        if (!messages.length) {
            return [];
        }
        const last = messages[messages.length - 1];
        return last.role === "assistant" && last.suggestions ? last.suggestions : [];
    }

    async sendSuggestion(text) {
        if (!text || this.state.sending) {
            return;
        }
        this.state.composerText = text;
        await this.sendMessage();
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
