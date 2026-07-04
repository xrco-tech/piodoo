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
        this.notification = useService("notification");
        this.state = useState({ status: "available" });
        onWillStart(async () => {
            try {
                const data = await this._rpc(
                    "/whatsapp/call/presence/get", {});
                if (data && data.presence) {
                    this.state.status = data.presence;
                }
            } catch (e) {
                console.warn("[wa-presence] initial fetch failed:", e);
            }
        });
    }

    _rpc(url, params) {
        return fetch(url, {
            method:      "POST",
            credentials: "same-origin",
            headers:     { "Content-Type": "application/json" },
            body:        JSON.stringify({
                jsonrpc: "2.0", method: "call", params: params || {},
                id: Math.floor(Math.random() * 1e9),
            }),
        }).then(r => r.json()).then(data => {
            if (data.error) {
                throw new Error(
                    (data.error.data && data.error.data.message) ||
                    data.error.message || "RPC error"
                );
            }
            return data.result;
        });
    }

    get cfg() {
        return CFG[this.state.status] || CFG.available;
    }

    async _cycle() {
        const ix = STATES.indexOf(this.state.status);
        const next = STATES[(ix + 1) % STATES.length];
        const previous = this.state.status;
        this.state.status = next;
        try {
            const result = await this._rpc(
                "/whatsapp/call/presence/set", { presence: next });
            if (!result?.success) {
                throw new Error(result?.error || "unknown");
            }
            this.notification.add(`Presence: ${CFG[next].label}`,
                                  { type: "info" });
        } catch (e) {
            // Roll back the optimistic update so the icon reflects
            // reality if the server rejected the change.
            this.state.status = previous;
            this.notification.add(
                "Could not update presence: " + (e?.message || e),
                { type: "danger" }
            );
        }
    }
}

registry.category("systray").add("comm_whatsapp_calling.SystrayPresence", {
    Component: WhatsAppSystrayPresence,
});
