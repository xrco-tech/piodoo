/** @odoo-module **/

/**
 * Systray dialer — a small phone-number input in the top bar so any
 * user can initiate an outbound WhatsApp call without hunting for a
 * partner record first. When more than one active WABA is configured,
 * a picker chooses which number to call from.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
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
            accounts: [],
            selectedAccountId: null,
        });
        onWillStart(async () => {
            try {
                const result = await this._rpc("/whatsapp/call/accounts", {});
                this.state.accounts = result?.accounts || [];
                this.state.selectedAccountId = result?.default_id || null;
            } catch (e) {
                console.warn("[wa-dialer] account fetch failed:", e);
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

    _toggle() {
        this.state.expanded = !this.state.expanded;
        if (this.state.expanded) {
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

    get selectedAccount() {
        if (!this.state.selectedAccountId) return null;
        return this.state.accounts.find(
            (a) => a.id === this.state.selectedAccountId
        ) || null;
    }

    get hasMultipleAccounts() {
        return this.state.accounts.length > 1;
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
            await svc.dialCall({
                toNumber:  to,
                accountId: this.state.selectedAccountId || null,
            });
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
