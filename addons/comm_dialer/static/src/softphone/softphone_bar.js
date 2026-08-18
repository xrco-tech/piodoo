/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/** Floating in-call bar. Registered as a main component so it renders at the app
 *  root (above all content, outside the navbar stacking context) — always
 *  clickable, never overlapping form views or crowding the navbar. */
export class DialerSoftphoneBar extends Component {
    static template = "comm_dialer.SoftphoneBar";
    static props = {};

    setup() {
        this.sp = useService("dialer_softphone");
        this.state = useState(this.sp.state);
    }

    get active() {
        return this.state.status === "ringing" || this.state.status === "incall";
    }

    toggleMute() {
        this.sp.toggleMute();
    }

    hangup() {
        this.sp.hangup();
    }
}

registry.category("main_components").add("comm_dialer.softphone_bar", {
    Component: DialerSoftphoneBar,
});
