/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODEL = "piodoo.ai.agent";

const STATUS = {
    draft: _t("Draft"),
    test: _t("Test only"),
    live: _t("Live"),
};

function when(value) {
    if (!value) {
        return "";
    }
    const at = deserializeDateTime(value);
    const days = Math.floor(-at.diffNow("days").days);
    if (days < 1 && at.hasSame(luxon.DateTime.local(), "day")) {
        return at.toFormat("HH:mm");
    }
    return days < 300 ? at.toFormat("d LLL") : at.toFormat("d LLL yyyy");
}

/** Every saved wording of one agent, newest first, each with "Use this one". */
class HistoryDialog extends Component {
    static template = "piodoo_ai.History";
    static components = { Dialog };
    static props = { versions: Array, restore: Function, close: Function };

    setup() {
        this.state = useState({ open: this.props.versions.length ? this.props.versions[0].id : false });
    }

    when(value) {
        return deserializeDateTime(value).toFormat("d LLL yyyy, HH:mm");
    }

    toggle(version) {
        this.state.open = this.state.open === version.id ? false : version.id;
    }

    async use(version) {
        await this.props.restore(version);
        this.props.close();
    }
}

export class AiAgents extends Component {
    static template = "piodoo_ai.App";
    static components = {};
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.threadRef = useRef("thread");
        this.state = useState({
            view: "home",
            agents: [],
            works: [],
            search: "",
            work: "",
            // One agent
            agent: null,
            text: "",
            saving: false,
            chats: [],
            chatSearch: "",
            chat: null,
            draft: "",
            asking: false,
            pending: "",
            error: "",
        });
        this.scrollDown = false;
        onWillStart(() => this.loadHome());
        const toEnd = () => {
            if (this.scrollDown && this.threadRef.el) {
                this.threadRef.el.scrollTop = this.threadRef.el.scrollHeight;
                this.scrollDown = false;
            }
        };
        onMounted(toEnd);
        onPatched(toEnd);
    }

    // ── Home ────────────────────────────────────────────────────────────────

    async loadHome() {
        const home = await this.orm.call(MODEL, "ui_home", []);
        this.state.agents = home.agents;
        this.state.works = home.works;
    }

    get shown() {
        const term = this.state.search.trim().toLowerCase();
        return this.state.agents.filter(
            (agent) =>
                (!this.state.work || agent.works.includes(this.state.work)) &&
                (!term || `${agent.name} ${agent.description}`.toLowerCase().includes(term))
        );
    }

    statusLabel(agent) {
        return STATUS[agent.status] || agent.status;
    }

    meta(agent) {
        const parts = [agent.model || _t("Model not set")];
        parts.push(agent.changed ? _t("wording changed %s", when(agent.changed_at)) : _t("as built"));
        return parts.join(" · ");
    }

    runs(agent) {
        const count = agent.usage.runs;
        return count === 1 ? _t("1 run") : _t("%s runs", count);
    }

    async goHome() {
        if (!(await this.leaveText())) {
            return;
        }
        this.state.view = "home";
        this.state.agent = null;
        await this.loadHome();
    }

    // ── One agent ───────────────────────────────────────────────────────────

    async open(agent) {
        const full = await this.orm.call(MODEL, "ui_agent", [agent.id]);
        Object.assign(this.state, {
            agent: full,
            text: full.instructions,
            chats: [],
            chatSearch: "",
            chat: null,
            draft: "",
            pending: "",
            error: "",
            asking: false,
            view: "agent",
        });
        if (full.chat && !full.chat_blocked) {
            await this.loadChats();
            if (this.state.chats.length) {
                await this.openChat(this.state.chats[0]);
            }
        }
    }

    get dirty() {
        return this.state.agent && this.state.text.trim() !== this.state.agent.instructions;
    }

    /** True when it is fine to leave the wording as it is on screen. */
    leaveText() {
        if (!this.dirty) {
            return Promise.resolve(true);
        }
        return new Promise((resolve) => {
            this.dialog.add(
                ConfirmationDialog,
                {
                    title: _t("Leave without saving?"),
                    body: _t("Your changes to what this agent is told have not been saved."),
                    confirmLabel: _t("Leave"),
                    cancelLabel: _t("Stay"),
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                },
                { onClose: () => resolve(false) }
            );
        });
    }

    setAgent(full) {
        this.state.agent = full;
        this.state.text = full.instructions;
    }

    async save() {
        if (!this.dirty || this.state.saving) {
            return;
        }
        this.state.saving = true;
        try {
            this.setAgent(await this.orm.call(MODEL, "ui_save", [this.state.agent.id, this.state.text]));
            this.notification.add(_t("Saved. The agent uses this from its next answer."), { type: "success" });
        } finally {
            this.state.saving = false;
        }
    }

    discard() {
        this.state.text = this.state.agent.instructions;
    }

    reset() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Back to as built?"),
            body: _t("The agent goes back to the wording it came with. Your wording stays in History."),
            confirmLabel: _t("Back to as built"),
            cancelLabel: _t("Cancel"),
            confirm: async () => {
                this.setAgent(await this.orm.call(MODEL, "ui_reset", [this.state.agent.id]));
            },
            cancel: () => {},
        });
    }

    async history() {
        const versions = await this.orm.call(MODEL, "ui_history", [this.state.agent.id]);
        this.dialog.add(HistoryDialog, {
            versions,
            restore: async (version) => {
                this.setAgent(await this.orm.call(MODEL, "ui_restore", [version.id]));
            },
        });
    }

    changedLine(agent) {
        if (!agent.changed) {
            return agent.versions ? _t("As built. Earlier wording is kept in History.") : _t("As built.");
        }
        return _t("Changed by %(who)s, %(when)s. Older versions are kept.", {
            who: agent.changed_by || _t("someone"),
            when: when(agent.changed_at),
        });
    }

    day(value) {
        return deserializeDate(value).toFormat("ccc d LLL");
    }

    // ── Chat ────────────────────────────────────────────────────────────────

    when(value) {
        return when(value);
    }

    async loadChats() {
        this.state.chats = await this.orm.call(MODEL, "ui_chats", [this.state.agent.id, this.state.chatSearch]);
    }

    async openChat(row) {
        const chat = await this.orm.call(MODEL, "ui_chat", [this.state.agent.id, row.id]);
        this.state.chat = chat || null;
        this.state.error = "";
        this.scrollDown = true;
    }

    newChat() {
        this.state.chat = null;
        this.state.error = "";
        this.state.draft = "";
    }

    onDraftKey(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.ask(this.state.draft);
        }
    }

    async ask(text) {
        text = (text || "").trim();
        if (!text || this.state.asking) {
            return;
        }
        Object.assign(this.state, { asking: true, pending: text, error: "", draft: "" });
        this.scrollDown = true;
        try {
            const chatId = this.state.chat ? this.state.chat.id : false;
            const chat = await this.orm.call(MODEL, "ui_ask", [this.state.agent.id, chatId, text]);
            if (chat.error) {
                this.state.error = chat.error;
                this.state.draft = text;
            } else {
                this.state.chat = chat;
                await this.loadChats();
            }
        } catch (error) {
            this.state.draft = text;
            throw error;
        } finally {
            this.state.asking = false;
            this.state.pending = "";
            this.scrollDown = true;
        }
    }

    /** The last message asks for a yes or no before anything is made. */
    isAsk(message) {
        const chat = this.state.chat;
        return chat.waiting && message === chat.messages[chat.messages.length - 1];
    }
}

registry.category("actions").add("piodoo_ai", AiAgents);
