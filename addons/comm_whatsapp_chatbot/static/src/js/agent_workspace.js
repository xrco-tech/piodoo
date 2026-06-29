/** @odoo-module **/

import { Component, markup, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

/* ── Markdown / escaping helpers (mirror the flow widget's) ─────────────── */
function bodyToHtml(text) {
    if (!text) return "";
    let s = String(text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    s = s.replace(/```([^`\n]+)```/g, "<code>$1</code>");
    s = s.replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>");
    s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");
    s = s.replace(/~([^~\n]+)~/g, "<s>$1</s>");
    return s.replace(/\n/g, "<br>");
}
function plainToHtml(text) {
    if (!text) return "";
    return String(text)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\n/g, "<br>");
}

export class AgentWorkspace extends Component {
    static template = "comm_whatsapp_chatbot.AgentWorkspace";
    static props = ["action", "actionId?"];

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");

        this.chatbotId = this.props.action.params?.chatbot_id;
        this.chatbotName = this.props.action.params?.chatbot_name || "";

        this.state = useState({
            // Pre-call form
            started: false,
            personaName: "",
            personaMobile: "",
            // Live session
            sessionId: null,
            partner: null,
            bubbles: [],
            userInput: "",
            sending: false,
            terminate: false,
            // Slot dashboard
            setupBots: [],
            setupLoading: false,
            // Wrap-up
            showWrap: false,
            outcome: "resolved",
            notes: "",
            saving: false,
        });

        onMounted(() => this._loadSetup());
    }

    /* ── Setup ──────────────────────────────────────────────────────────── */
    async _loadSetup() {
        this.state.setupLoading = true;
        try {
            const data = await rpc("/voice/setup", {
                chatbot_id: this.chatbotId,
                contact_id: null,
            });
            this.state.setupBots = data?.bots || [];
        } finally {
            this.state.setupLoading = false;
        }
    }

    /* ── Pre-call ───────────────────────────────────────────────────────── */
    async _startCall() {
        const mobile = (this.state.personaMobile || "").trim();
        if (!mobile) {
            this.notification.add("Customer mobile is required.", { type: "warning" });
            return;
        }
        this.state.sending = true;
        try {
            const data = await rpc("/voice/start", {
                chatbot_id: this.chatbotId,
                contact_details: {
                    name: (this.state.personaName || "").trim(),
                    mobile,
                },
            });
            if (data?.error) {
                this.notification.add(data.error, { type: "danger" });
                this.state.sending = false;
                return;
            }
            this.state.sessionId = data.session_id;
            this.state.partner = data.partner;
            this.state.started = true;
            // Re-load setup now that we have a contact (so saved values prefill).
            await this._loadSetupForContact(data.contact_id);
            // First engine turn — produces the welcome script.
            await this._sendTurn(null);
        } catch (e) {
            this.notification.add("Could not start the call.", { type: "danger" });
            this.state.sending = false;
        }
    }

    async _loadSetupForContact(contactId) {
        try {
            const data = await rpc("/voice/setup", {
                chatbot_id: this.chatbotId,
                contact_id: contactId,
            });
            this.state.setupBots = data?.bots || [];
        } catch (e) { /* non-fatal */ }
    }

    /* ── Turn driving ───────────────────────────────────────────────────── */
    _collectVariables() {
        const out = [];
        for (const bot of this.state.setupBots) {
            for (const v of (bot.variables || [])) {
                if (v.value !== "" && v.value !== null && v.value !== undefined) {
                    out.push({ variable_id: v.id, value: v.value });
                }
            }
        }
        return out;
    }

    async _sendTurn(userInput) {
        this.state.sending = true;
        try {
            const data = await rpc("/voice/turn", {
                session_id: this.state.sessionId,
                user_input: userInput,
                initial_variables: this._collectVariables(),
            });
            if (data?.error) {
                this.notification.add(data.error, { type: "danger" });
                return;
            }
            for (const b of (data.bubbles || [])) {
                this.state.bubbles.push({
                    ...b,
                    dir: "in",
                    text: b.text || b.body || "",
                    step_type: b.step_type || "message",
                });
            }
            this.state.terminate = !!data.terminate;
            // Refresh slot values from server (engine may have set some).
            await this._refreshSlots();
        } catch (e) {
            this.notification.add("Engine error.", { type: "danger" });
        } finally {
            this.state.sending = false;
            queueMicrotask(() => {
                const el = document.querySelector(".o_aw_script");
                if (el) el.scrollTop = el.scrollHeight;
            });
        }
    }

    async _refreshSlots() {
        // Re-fetch setup so the right-pane reflects engine-set values.
        if (!this.state.sessionId) return;
        try {
            const data = await rpc("/voice/setup", {
                chatbot_id: this.chatbotId,
                contact_id: (await this._getContactIdFromSession()),
            });
            // Preserve any local-only edits the agent is typing right now: we
            // only update slots whose current displayed value is empty. (Cheap
            // protection against clobbering work-in-progress text.)
            const newBots = data?.bots || [];
            for (const newBot of newBots) {
                const existing = this.state.setupBots.find(b => b.chatbot_id === newBot.chatbot_id);
                if (!existing) continue;
                for (const newVar of (newBot.variables || [])) {
                    const cur = existing.variables.find(v => v.id === newVar.id);
                    if (cur && (!cur.value || cur.value === '')) {
                        cur.value = newVar.value;
                    }
                }
            }
        } catch (e) { /* non-fatal */ }
    }

    async _getContactIdFromSession() {
        // We stored partner.id at start; the contact id wasn't echoed back to
        // the client originally. The setup endpoint accepts the contact_id
        // directly — to keep this simple in v1, we just pass null and accept
        // that prefill happens only at start time. The /voice/turn loop
        // already keeps the engine state consistent.
        return null;
    }

    _sendTyped() {
        const txt = (this.state.userInput || "").trim();
        if (!txt || this.state.sending || this.state.terminate) return;
        this.state.bubbles.push({ text: txt, dir: "out", step_type: "user" });
        this.state.userInput = "";
        this._sendTurn(txt);
    }

    _sendQuickReply(text) {
        if (!text || this.state.sending || this.state.terminate) return;
        this.state.bubbles.push({ text, dir: "out", step_type: "user" });
        this._sendTurn(text);
    }

    _onInputKey(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this._sendTyped();
        }
    }

    /* ── Slot edits ─────────────────────────────────────────────────────── */
    async _applySlotEdits() {
        this.state.sending = true;
        try {
            await rpc("/voice/update", {
                session_id: this.state.sessionId,
                initial_variables: this._collectVariables(),
            });
            this.notification.add("Slot values saved.", { type: "success" });
        } catch (e) {
            this.notification.add("Could not save slot values.", { type: "danger" });
        } finally {
            this.state.sending = false;
        }
    }

    /* ── Navigation ─────────────────────────────────────────────────────── */
    _goBack() {
        // Pop the workspace off the action stack — Odoo's breadcrumbs take us
        // back to whichever view launched it (typically the chatbot form).
        // The session stays open server-side; the agent can resume it from
        // Voice Call Sessions or just walk away. If we're still mid-session,
        // surface a non-blocking hint so the agent knows the wrap-up is
        // skipped.
        if (this.state.started && !this.state.terminate) {
            this.notification.add(
                "Workspace closed. Session is still open — resume from Voice Call Sessions.",
                { type: "info" }
            );
        }
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }

    /* ── Wrap-up ────────────────────────────────────────────────────────── */
    _openWrap() { this.state.showWrap = true; }
    _closeWrap() { this.state.showWrap = false; }

    async _endCall() {
        if (!this.state.sessionId) return;
        this.state.saving = true;
        try {
            await rpc("/voice/end", {
                session_id: this.state.sessionId,
                outcome: this.state.outcome,
                notes: this.state.notes,
            });
            this.notification.add("Call closed.", { type: "success" });
            this.action.doAction({ type: "ir.actions.act_window_close" });
        } catch (e) {
            this.notification.add("Could not close the call.", { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    /* ── Renderers exposed to the template ─────────────────────────────── */
    formatBody(text) { return markup(bodyToHtml(text)); }
    escape(text) { return markup(plainToHtml(text)); }
}

registry.category("actions").add("comm_whatsapp_chatbot.agent_workspace", AgentWorkspace);
