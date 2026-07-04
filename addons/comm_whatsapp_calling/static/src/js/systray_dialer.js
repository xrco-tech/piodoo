/** @odoo-module **/

/**
 * Systray dialer — a small phone-number input in the top bar so any
 * user can initiate an outbound WhatsApp call without hunting for a
 * partner record first.
 */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WhatsAppSystrayDialer extends Component {
    static template = "comm_whatsapp_calling.SystrayDialer";
    static props = {};

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            expanded: false,
            toNumber: "",
            dialing: false,
        });
        // The service registers itself lazily; look it up on click.
        this.env = this.env;
    }

    _toggle() {
        this.state.expanded = !this.state.expanded;
        if (this.state.expanded) {
            // Focus the input after DOM update.
            setTimeout(() => {
                const el = document.querySelector(".o_wa_dialer_input");
                el && el.focus();
            }, 0);
        }
    }

    _onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this._dial();
        }
    }

    async _dial() {
        const to = (this.state.toNumber || "").trim();
        if (!to) {
            this.notification.add("Enter a number to dial.", { type: "warning" });
            return;
        }
        this.state.dialing = true;
        try {
            const svc = this.env.services.comm_whatsapp_calling;
            if (!svc || typeof svc.dialCall !== "function") {
                this.notification.add(
                    "Calling service not available.", { type: "danger" });
                return;
            }
            await svc.dialCall({ toNumber: to });
            this.state.expanded = false;
            this.state.toNumber = "";
        } finally {
            this.state.dialing = false;
        }
    }
}

registry.category("systray").add("comm_whatsapp_calling.SystrayDialer", {
    Component: WhatsAppSystrayDialer,
});
