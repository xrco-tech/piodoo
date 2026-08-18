/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/** Systray: just the status icon + coloured dot. Call controls live in the
 *  floating bar (main component) so they never crowd the navbar. */
export class DialerSoftphoneSystray extends Component {
    static template = "comm_dialer.SoftphoneSystray";
    static props = {};

    setup() {
        this.state = useState(useService("dialer_softphone").state);
    }

    get dotClass() {
        return {
            registered: "o_sp_ok",
            incall: "o_sp_incall",
            ringing: "o_sp_ring",
            connecting: "o_sp_wait",
            unregistered: "o_sp_off",
            failed: "o_sp_err",
            idle: "o_sp_off",
        }[this.state.status] || "o_sp_off";
    }

    get statusLabel() {
        return {
            registered: "Softphone ready",
            incall: "On call",
            ringing: "Incoming call",
            connecting: "Connecting…",
            unregistered: "Not registered",
            failed: "Softphone error",
            idle: "Idle",
        }[this.state.status] || "Softphone";
    }
}

registry.category("systray").add(
    "comm_dialer.softphone",
    { Component: DialerSoftphoneSystray },
    { sequence: 20 }
);
