/** @odoo-module **/

/**
 * Systray presence dropdown — sets the current user's
 * res.users.wa_call_presence to Available / Away / Do Not Disturb.
 * Away and DND users are skipped when the inbound webhook broadcasts a
 * ringing event, so their browsers stay quiet.
 *
 * Positioning/outside-click/backdrop-filter workaround mirrors
 * systray_whatsapp_calls.js's dropdown — see that file's comments for
 * why the fixed-position panel needs the body-class toggle.
 */

import { Component, useState, onWillStart, onMounted, onWillUnmount, onPatched } from "@odoo/owl";
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
    static DROPDOWN_LAYER_Z = 12000;

    setup() {
        this.notification = useService("notification");
        this.state = useState({ status: "available", open: false, dropdownPos: null });

        this._onAway = (ev) => {
            if (!this.state.open || !this.el) return;
            if (ev.button !== 0 && ev.button !== undefined) return;
            if (this._eventIsInsideUi(ev)) return;
            this._close();
        };
        this._repositionScheduled = false;
        this._onReposition = () => {
            if (!this.state.open) return;
            if (this._repositionScheduled) return;
            this._repositionScheduled = true;
            requestAnimationFrame(() => {
                this._repositionScheduled = false;
                this._syncDropdownViewport();
            });
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
            window.addEventListener("scroll", this._onReposition, true);
            window.addEventListener("resize", this._onReposition);
        });
        onWillUnmount(() => {
            window.removeEventListener("pointerdown", this._onAway, true);
            window.removeEventListener("scroll", this._onReposition, true);
            window.removeEventListener("resize", this._onReposition);
            this._setBodyDropdownOpen(false);
        });
        onPatched(() => {
            if (this.state.open) this._syncDropdownViewport();
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

    _presenceBtnEl() {
        return this.el?.querySelector(".o_wa_presence_btn") || this.el;
    }

    _syncDropdownViewport() {
        const anchor = this._presenceBtnEl();
        if (!anchor) return;
        const r = anchor.getBoundingClientRect();
        const doc = document.documentElement;
        const top = Math.round(r.bottom + 6);
        const right = Math.round(doc.clientWidth - r.right);
        const prev = this.state.dropdownPos;
        if (prev && prev.top === top && prev.right === right) return;
        this.state.dropdownPos = { top, right };
    }

    dropdownLayerStyle() {
        if (!this.state.open) return "";
        const p = this.state.dropdownPos;
        const top = p?.top ?? 52;
        const right = p?.right ?? 12;
        return `position:fixed;top:${top}px;right:${right}px;left:auto;z-index:${WhatsAppSystrayPresence.DROPDOWN_LAYER_Z};`;
    }

    _close() {
        this.state.open = false;
        this.state.dropdownPos = null;
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
        this._syncDropdownViewport();
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
