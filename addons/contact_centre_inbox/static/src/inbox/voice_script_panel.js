/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class VoiceScriptPanel extends Component {
    static template = "contact_centre_inbox.VoiceScriptPanel";
    static props = {
        sessionId: [String, Number],
        chatbotName: String,
        onEnd: Function,
    };

    setup() {
        this.callingService = this.env.services.comm_whatsapp_calling;
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            bubbles: [],
            terminated: false,
            inputText: "",
        });

        onWillStart(() => this.sendTurn(null));
    }

    async sendTurn(userInput) {
        this.state.loading = true;
        try {
            const data = await rpc("/voice/turn", {
                session_id: this.props.sessionId,
                user_input: userInput,
                initial_variables: {},
            });
            this.state.bubbles = this.state.bubbles.concat(data.bubbles || []);
            this.state.terminated = !!data.terminate;
        } catch (_e) {
            this.notification.add("Voice script error — the turn failed to advance.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    clickOption(text) {
        this.sendTurn(text);
    }

    submitFreeText() {
        const text = this.state.inputText.trim();
        if (!text) {
            return;
        }
        this.state.inputText = "";
        this.sendTurn(text);
    }

    onInputChange(ev) {
        this.state.inputText = ev.target.value;
    }

    async endCall() {
        try {
            await rpc("/voice/end", { session_id: this.props.sessionId });
        } catch (_e) {
            // Best-effort — still hang up and close the panel below.
        }
        if (this.callingService && this.callingService.isActive && this.callingService.isActive()) {
            this.callingService.hangupActive();
        }
        this.props.onEnd();
    }
}
