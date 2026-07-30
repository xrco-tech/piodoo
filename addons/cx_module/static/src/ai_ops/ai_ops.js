/** @odoo-module **/

import { Component, useState, useRef, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class CxAiOps extends Component {
    static template = "cx_module.AiOps";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            messages: [
                {
                    role: "assistant",
                    content: "Hi — I can help you draft outbound campaigns. " +
                        "Everything I create stays in draft; you launch it yourself.",
                },
            ],
            suggestions: [],
            input: "",
            busy: false,
        });
        this.threadRef = useRef("thread");
        useEffect(
            () => {
                const el = this.threadRef.el;
                if (el) el.scrollTop = el.scrollHeight;
            },
            () => [this.state.messages.length, this.state.busy]
        );
    }

    onInput(ev) {
        this.state.input = ev.target.value;
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async pickSuggestion(text) {
        this.state.input = text;
        await this.send();
    }

    async send() {
        const text = this.state.input.trim();
        if (!text || this.state.busy) {
            return;
        }
        this.state.messages.push({ role: "user", content: text });
        this.state.input = "";
        this.state.suggestions = [];
        this.state.busy = true;
        // Send only role+text history; the backend runs the tool loop.
        const history = this.state.messages.map((m) => ({ role: m.role, content: m.content }));
        try {
            const res = await this.orm.call("cx.ai.ops", "chat", [history]);
            this.state.messages.push({ role: "assistant", content: res.reply || "" });
            this.state.suggestions = res.suggestions || [];
        } catch (e) {
            this.state.messages.push({
                role: "assistant",
                content: "Something went wrong reaching the assistant.",
            });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("cx_ai_ops", CxAiOps);
