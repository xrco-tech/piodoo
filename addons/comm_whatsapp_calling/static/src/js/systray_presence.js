/** @odoo-module **/

/**
 * Systray presence dropdown — sets the current user's
 * res.users.wa_call_presence to Available / Away / Do Not Disturb.
 * Away and DND users are skipped when the inbound webhook broadcasts a
 * ringing event, so their browsers stay quiet.
 *
 * The dropdown panel is a plain CSS-anchored child (position:absolute
 * under the button) rather than the viewport-computed position:fixed
 * panel systray_whatsapp_calls.js uses — that one needs JS math because
 * its panel is meant to align with a badge that can sit anywhere in a
 * wider icon cluster; this one only ever needs to hang directly under
 * its own button, so plain CSS does it with nothing to get out of sync.
 * It still needs the same backdrop-filter workaround (see CSS) since
 * home-theme's .o_main_navbar glass effect traps any descendant that's
 * meant to paint above it, positioned or not.
 */

import { Component, useState, onMounted, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATES = ["available", "away", "dnd"];
const CFG = {
    available: { icon: "fa-circle",       cls: "o_wa_status_available", label: "Available" },
    away:      { icon: "fa-circle-o",     cls: "o_wa_status_away",      label: "Away" },
    dnd:       { icon: "fa-minus-circle", cls: "o_wa_status_dnd",       label: "Do not disturb" },
};

class WhatsAppSystrayPresence extends Component {
    static template = "comm_whatsapp_calling.SystrayPresence";
    static props = {};

    setup() {
        this.notification = useService("notification");
        this.state = useState({ status: "available", open: false });

        this._onAway = (ev) => {
            if (!this.state.open || !this.el) return;
            if (ev.button !== 0 && ev.button !== undefined) return;
            if (this._eventIsInsideUi(ev)) return;
            this._close();
        };

        onWillStart(async () => {
            try {
                const data = await this._rpc("/whatsapp/call/presence/get", {});
                if (data && data.presence) this.state.status = data.presence;
            } catch (e) {
                console.warn("[wa-presence] initial fetch failed:", e);
            }
        });

        onMounted(() => {
            window.addEventListener("pointerdown", this._onAway, true);
        });
        onWillUnmount(() => {
            window.removeEventListener("pointerdown", this._onAway, true);
            this._setBodyDropdownOpen(false);
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

    get states() {
        return STATES.map((key) => ({ key, ...CFG[key], active: key === this.state.status }));
    }

    _setBodyDropdownOpen(active) {
        if (typeof document !== "undefined" && document.body) {
            document.body.classList.toggle("o_wa_presence_dropdown_open", Boolean(active));
        }
    }

    _eventIsInsideUi(ev) {
        const root = this.el;
        if (!root) return false;
        const t = ev.target;
        if (t instanceof Node && root.contains(t)) return true;
        const path = ev.composedPath?.();
        if (path) {
            for (const n of path) {
                if (n === root) return true;
            }
        }
        return false;
    }

    _close() {
        this.state.open = false;
        this._setBodyDropdownOpen(false);
    }

    onToggleClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        // Piggyback on this click (a real user gesture — browsers ignore
        // requestPermission() called any other way, e.g. from the bus
        // event when a call actually rings in) to ask for desktop
        // notification permission before the agent ever needs it.
        this.env.services.comm_whatsapp_calling?.ensureNotificationPermission?.();
        if (this.state.open) {
            this._close();
            return;
        }
        this.state.open = true;
        this._setBodyDropdownOpen(true);
    }

    onDropdownClick(ev) {
        ev.stopPropagation();
    }

    async onSelect(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const next = ev.currentTarget?.dataset?.presence;
        this._close();
        if (!next || !CFG[next] || next === this.state.status) return;

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
