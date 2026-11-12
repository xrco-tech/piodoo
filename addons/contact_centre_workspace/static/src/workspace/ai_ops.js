/** @odoo-module **/

import { Component, useState, useRef, useEffect, onWillStart, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { when } from "./util";
import { markdownToHtml } from "./markdown";

const WS = "contact.centre.workspace";
const CHAT = "contact.centre.ai.chat";
const PAGE = 40;

// What a change made by the copilot touched: the record's model and where its
// id is in the result. Campaigns, contacts and templates open in their own
// section of the workspace; the rest open as a form.
const RECORDS = {
    campaign: { model: "contact.centre.campaign", key: "campaign_id", section: "campaigns" },
    contact: { model: "contact.centre.contact", key: "contact_id", section: "contacts" },
    template: { model: "contact.centre.template", key: "template_id", section: "templates" },
    whatsapp_template: { model: "whatsapp.template", key: "template_id" },
    call_team: { model: "whatsapp.call.team", key: "team_id" },
    call_routing_rule: { model: "whatsapp.call.routing.rule", key: "rule_id" },
    chatbot_flow: { model: "whatsapp.chatbot", key: "chatbot_id" },
    dashboard_card: { model: "contact.centre.dashboard.card", key: "card_id" },
};
const VERBS = { create: _t("Create"), update: _t("Update"), delete: _t("Delete"), list: _t("Look up"), search: _t("Look up") };

/** The AI Ops section: chats with the copilot, and what it did in each. */
export class ContactCentreAiOps extends Component {
    static template = "contact_centre_workspace.AiOps";
    static props = {
        boot: Object,
        setPane: Function,
        goTo: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            search: "",
            rows: [],
            total: 0,
            more: false,
            loading: true,
            sel: false,
            chat: null,
            loadingChat: false,
            infoOpen: true,
            text: "",
            sending: false,
            renaming: false,
            renameText: "",
            open: {},              // action id -> its details are showing
            lookups: false,        // look-ups are folded away unless asked for
        });
        this.when = when;
        this.threadRef = useRef("thread");
        this.composerRef = useRef("composer");
        useEffect(() => this.scrollToEnd(), () => [this.state.chat && this.state.chat.messages, this.state.sending]);
        useEffect(() => this.growComposer(), () => [this.state.text]);
        this.searchLater = useDebounced(() => this.loadList(), 300);
        onWillStart(() => this.loadList());
    }

    // ── Loading ──────────────────────────────────────────────────────────
    async loadList(limit = PAGE) {
        this.state.loading = true;
        try {
            const result = await this.orm.call(WS, "ws_ai_chats", [], { search: this.state.search, offset: 0, limit });
            this.state.rows = result.rows;
            this.state.total = result.total;
            this.state.more = result.more;
        } finally {
            this.state.loading = false;
        }
    }

    async loadMore() {
        const result = await this.orm.call(WS, "ws_ai_chats", [], {
            search: this.state.search, offset: this.state.rows.length, limit: PAGE,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async loadChat(id) {
        const chat = await this.orm.call(WS, "ws_ai_chat", [id]);
        if (this.state.sel === id) {
            this.state.chat = chat;
        }
    }

    async open(id) {
        this.state.sel = id;
        this.state.renaming = false;
        this.state.text = "";
        this.state.open = {};
        this.props.setPane("thread");
        this.state.loadingChat = !this.state.chat;
        try {
            await this.loadChat(id);
        } finally {
            this.state.loadingChat = false;
        }
    }

    async newChat() {
        const id = await this.orm.call(WS, "ws_ai_new_chat", []);
        await Promise.all([this.loadList(), this.open(id)]);
        if (this.composerRef.el) {
            this.composerRef.el.focus();
        }
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchLater();
    }

    get totalText() {
        const total = this.state.total;
        return total === 1 ? _t("1 chat") : _t("%s chats", total);
    }

    // ── The chat ─────────────────────────────────────────────────────────
    html(text) {
        // Safe to render as HTML: markdownToHtml escapes the text before adding any tags.
        return markup(markdownToHtml(text));
    }

    /** Quick replies offered with the copilot's latest message. */
    get suggestions() {
        const messages = this.state.chat.messages;
        const last = messages[messages.length - 1];
        return last && !last.mine && !this.state.sending ? last.suggestions : [];
    }

    get heldText() {
        const held = this.state.chat.held;
        if (!held.length) {
            return "";
        }
        const names = held.map((call) => this.toolLabel(call.tool).toLowerCase()).join(", ");
        return held.length === 1
            ? _t("Waiting for your go-ahead to %s. Nothing changes until you say yes.", names)
            : _t("Waiting for your go-ahead on %(count)s changes (%(names)s). Nothing changes until you say yes.", { count: held.length, names });
    }

    scrollToEnd() {
        const el = this.threadRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    growComposer() {
        const el = this.composerRef.el;
        if (el) {
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
        }
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

    suggest(text) {
        this.state.text = text;
        this.send();
    }

    /** One round trip: it stores the message and comes back when the copilot has answered. */
    async send() {
        const text = this.state.text.trim();
        const id = this.state.sel;
        if (!text || !id || this.state.sending) {
            return;
        }
        this.state.text = "";
        this.state.sending = true;
        // Shown at once: the reply can take a while.
        this.state.chat.messages = this.state.chat.messages.concat({ id: `local-${Date.now()}`, mine: true, content: text, suggestions: [] });
        try {
            await this.orm.silent.call(CHAT, "send_message", [[id], text]);
        } catch {
            this.notification.add(_t("The copilot did not answer. Your message is in the chat; try again in a moment."), { type: "danger" });
        } finally {
            this.state.sending = false;
            await Promise.all([this.loadChat(id), this.loadList(Math.max(PAGE, this.state.rows.length))]);
        }
    }

    // ── Renaming ─────────────────────────────────────────────────────────
    rename() {
        this.state.renaming = true;
        this.state.renameText = this.state.chat.name;
    }

    onRenameText(ev) {
        this.state.renameText = ev.target.value;
    }

    onRenameKey(ev) {
        if (ev.key === "Enter") {
            this.saveName();
        } else if (ev.key === "Escape") {
            this.state.renaming = false;
        }
    }

    async saveName() {
        const name = this.state.renameText.trim();
        this.state.renaming = false;
        if (!name || name === this.state.chat.name) {
            return;
        }
        this.state.chat.name = await this.orm.call(WS, "ws_ai_rename", [this.state.sel, name]);
        const row = this.state.rows.find((r) => r.id === this.state.sel);
        if (row) {
            row.name = this.state.chat.name;
        }
    }

    // ── What the copilot did ─────────────────────────────────────────────
    /** "create_campaign" → "Create campaign". */
    toolLabel(tool) {
        const [verb, ...rest] = (tool || "").split("_");
        const noun = rest.join(" ");
        return VERBS[verb] ? `${VERBS[verb]} ${noun}` : (tool || "").replace(/_/g, " ");
    }

    isLookup(action) {
        return /^(list|search)_/.test(action.tool);
    }

    /** Changes first-class; look-ups only when asked for. */
    get actions() {
        const actions = this.state.chat.actions;
        return this.state.lookups ? actions : actions.filter((action) => !this.isLookup(action));
    }

    get lookupCount() {
        return this.state.chat.actions.filter((action) => this.isLookup(action)).length;
    }

    toggleLookups() {
        this.state.lookups = !this.state.lookups;
    }

    outcome(action) {
        if (action.declined) {
            return { label: _t("Not done"), cls: "plain" };
        }
        return action.ok ? { label: _t("Done"), cls: "ok" } : { label: _t("Failed"), cls: "warn" };
    }

    /** Why it failed or was not done, in the copilot's own words. */
    reason(action) {
        const result = action.result || {};
        return action.declined ? _t("You did not confirm it.") : (!action.ok && result.error) || "";
    }

    /** The record a finished change touched, or null. */
    target(action) {
        if (!action.ok || action.declined) {
            return null;
        }
        const match = /^(?:create|update)_(.+)$/.exec(action.tool);
        const record = match && RECORDS[match[1]];
        const id = record && action.result && action.result[record.key];
        return typeof id === "number" ? { ...record, id } : null;
    }

    openTarget(action) {
        const target = this.target(action);
        if (target.section) {
            this.props.goTo(target.section, target.id);
        } else {
            this.action.doAction({
                type: "ir.actions.act_window", res_model: target.model, res_id: target.id, views: [[false, "form"]], target: "new",
            });
        }
    }

    toggleAction(action) {
        this.state.open[action.id] = !this.state.open[action.id];
    }

    json(value) {
        return JSON.stringify(value, null, 2);
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    showChat() {
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
}
