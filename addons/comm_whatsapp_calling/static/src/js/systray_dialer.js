/** @odoo-module **/

/**
 * Systray dialer — a phone icon in the top bar that opens the shared
 * VoIP-card "New Call" widget (built in incoming_call_popup.js, same
 * look/theme as the incoming-call popup and the in-call HUD).
 */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class WhatsAppSystrayDialer extends Component {
    static template = "comm_whatsapp_calling.SystrayDialer";
    static props = {};

    setup() {
        this.notification = useService("notification");
    }

    _openDialPad() {
        const svc = this.env.services.comm_whatsapp_calling;
        if (!svc || typeof svc.openDialPad !== "function") {
            this.notification.add(
                "Calling service not available.", { type: "danger" });
            return;
        }
        svc.openDialPad();
    }
}

registry.category("systray").add("comm_whatsapp_calling.SystrayDialer", {
    Component: WhatsAppSystrayDialer,
});
