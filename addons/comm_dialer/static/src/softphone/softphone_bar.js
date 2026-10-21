/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const KEYPAD = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

/** Floating in-call bar. Registered as a main component so it renders at the app
 *  root (above all content, outside the navbar stacking context) — always
 *  clickable, never overlapping form views or crowding the navbar. */
export class DialerSoftphoneBar extends Component {
    static template = "comm_dialer.SoftphoneBar";
    static props = {};

    setup() {
        this.sp = useService("dialer_softphone");
        this.action = useService("action");
        this.state = useState(this.sp.state);
        this.keypad = KEYPAD;
        this.dial = useState({ value: "" });
        // Script / campaign picker above the bar + the script answer box.
        this.ui = useState({ picker: null, items: [], loading: false, answer: "" });
    }

    get active() {
        return ["ringing", "connecting", "calling", "incall"].includes(this.state.status);
    }

    get stateLabel() {
        return {
            ringing: "Incoming call",
            connecting: "Connecting…",
            calling: "Calling…",
            incall: "On call",
        }[this.state.status] || "";
    }

    // True only when the softphone has registered to Asterisk and can place a call.
    get canCall() {
        return this.state.status === "registered";
    }

    // Friendly connection status shown in the pad when we can't yet dial.
    get connLabel() {
        return {
            connecting: "Connecting to the phone server…",
            unregistered: "Not registered with the phone server.",
            failed: "Can't reach the phone server — check the VoIP connection.",
            idle: "Softphone not connected yet.",
        }[this.state.status] || "";
    }

    press(d) {
        this.dial.value += d;
    }

    backspace() {
        this.dial.value = this.dial.value.slice(0, -1);
    }

    callNow() {
        if (!this.canCall) {
            return;
        }
        const number = this.dial.value.trim();
        if (number) {
            this.sp.dial(number);
            this.dial.value = "";
        }
    }

    closeDialer() {
        this.sp.toggleDialer();
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.callNow();
        }
    }

    toggleMute() {
        this.sp.toggleMute();
    }

    hangup() {
        this.sp.hangup();
    }

    accept() {
        this.sp.accept();
    }

    decline() {
        this.sp.decline();
    }

    toggleRecord() {
        this.sp.toggleRecord();
    }

    // ── Call script + campaign (mirrors the WhatsApp call popup) ─────────
    async openPicker(kind) {
        if (this.ui.picker === kind) {
            this.closePicker();
            return;
        }
        this.ui.picker = kind;
        this.ui.items = [];
        this.ui.loading = true;
        try {
            this.ui.items = kind === "script"
                ? await this.sp.scriptOptions()
                : await this.sp.campaignOptions();
        } catch {
            this.ui.items = [];
        } finally {
            this.ui.loading = false;
        }
    }

    closePicker() {
        this.ui.picker = null;
        this.ui.items = [];
    }

    pick(item) {
        const kind = this.ui.picker;
        this.closePicker();
        if (kind === "script") {
            this.sp.startScript(item.id, item.name);
        } else if (kind === "campaign" && !item.already) {
            this.sp.addToCampaign(item.id);
        }
    }

    scriptAnswer(text) {
        text = (text || "").trim();
        if (text) {
            this.ui.answer = "";
            this.sp.scriptTurn(text);
        }
    }

    onScriptKeydown(ev) {
        if (ev.key === "Enter") {
            this.scriptAnswer(this.ui.answer);
        }
    }

    closeScript() {
        this.sp.closeScript();
    }

    // Open the transfer wizard for the current call (blind transfer for now).
    async transfer() {
        const callId = this.sp.callId;
        if (!callId) {
            return;
        }
        await this.action.doAction("comm_dialer.action_transfer_wizard", {
            additionalContext: { default_call_id: callId },
        });
    }
}

registry.category("main_components").add("comm_dialer.softphone_bar", {
    Component: DialerSoftphoneBar,
});
