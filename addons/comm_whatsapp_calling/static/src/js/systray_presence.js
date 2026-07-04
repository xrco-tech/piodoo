/** @odoo-module **/

/**
 * Systray presence toggle — cycles the current user's
 * res.users.wa_call_presence between Available / Away / Do Not Disturb.
 * Away and DND users are skipped when the inbound webhook broadcasts a
 * ringing event, so their browsers stay quiet.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATES = ["available", "away", "dnd"];
const CFG = {
    available: { icon: "fa-circle",       color: "#25D366", label: "Available" },
    away:      { icon: "fa-circle-o",     color: "#f59e0b", label: "Away" },
    dnd:       { icon: "fa-minus-circle", color: "#dc2626", label: "Do not disturb" },
};

class WhatsAppSystrayPresence extends Component {
    static template = "comm_whatsapp_calling.SystrayPresence";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ status: "available" });
        onWillStart(async () => {
            try {
                const uid = this.env.services.user?.userId
                          || this.env.services?.uid;
                if (!uid) return;
                const [rec] = await this.orm.read(
                    "res.users", [uid], ["wa_call_presence"]);
                if (rec && rec.wa_call_presence) {
                    this.state.status = rec.wa_call_presence;
                }
            } catch (e) {
                console.warn("[wa-presence] initial fetch failed:", e);
            }
        });
    }

    get cfg() {
        return CFG[this.state.status] || CFG.available;
    }

    async _cycle() {
        const ix = STATES.indexOf(this.state.status);
        const next = STATES[(ix + 1) % STATES.length];
        this.state.status = next;
        try {
            const uid = this.env.services.user?.userId
                     || this.env.services?.uid;
            await this.orm.write("res.users", [uid], {
                wa_call_presence: next,
            });
            this.notification.add(`Presence: ${CFG[next].label}`,
                                  { type: "info" });
        } catch (e) {
            this.notification.add("Could not update presence.",
                                  { type: "danger" });
        }
    }
}

registry.category("systray").add("comm_whatsapp_calling.SystrayPresence", {
    Component: WhatsAppSystrayPresence,
});
