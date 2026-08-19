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
        this.state = useState(this.sp.state);
        this.keypad = KEYPAD;
        this.dial = useState({ value: "" });
    }

    get active() {
        return ["ringing", "calling", "incall"].includes(this.state.status);
    }

    get stateLabel() {
        return {
            ringing: "Incoming call",
            calling: "Calling…",
            incall: "On call",
        }[this.state.status] || "";
    }

    press(d) {
        this.dial.value += d;
    }

    backspace() {
        this.dial.value = this.dial.value.slice(0, -1);
    }

    callNow() {
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
}

registry.category("main_components").add("comm_dialer.softphone_bar", {
    Component: DialerSoftphoneBar,
});
