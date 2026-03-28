/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onWillUnmount, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WhatsAppCallsSystray extends Component {
    static template = "comm_whatsapp_calling.WhatsAppCallsSystray";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            unansweredCount: 0,
            open: false,
            items: [],
            /** Viewport placement for fixed dropdown (escapes navbar stacking context). */
            dropdownPos: null,
        });

        this._repositionScheduled = false;
        this._onDocClick = (ev) => {
            if (!this.state.open || !this.el) {
                return;
            }
            if (this.el.contains(ev.target)) {
                return;
            }
            this.state.open = false;
            this.state.dropdownPos = null;
        };

        onWillStart(async () => {
            await this.refreshCounts();
        });

        this._onReposition = () => {
            if (!this.state.open) {
                return;
            }
            if (this._repositionScheduled) {
                return;
            }
            this._repositionScheduled = true;
            requestAnimationFrame(() => {
                this._repositionScheduled = false;
                this._layoutDropdown();
            });
        };

        onMounted(() => {
            document.addEventListener("click", this._onDocClick, true);
            window.addEventListener("scroll", this._onReposition, true);
            window.addEventListener("resize", this._onReposition);
        });

        onWillUnmount(() => {
            document.removeEventListener("click", this._onDocClick, true);
            window.removeEventListener("scroll", this._onReposition, true);
            window.removeEventListener("resize", this._onReposition);
        });

        onPatched(() => {
            if (this.state.open) {
                this._layoutDropdown();
            }
        });
    }

    /** z-index above action manager / home dashboard tiles (Discuss-style elevation). */
    static DROPDOWN_Z = 1100;

    _layoutDropdown() {
        const anchor = this.el?.querySelector(".o_wa_calls_systray");
        if (!anchor) {
            return;
        }
        const r = anchor.getBoundingClientRect();
        const top = Math.round(r.bottom + 6);
        const doc = document.documentElement;
        const right = Math.round(doc.clientWidth - r.right);
        const prev = this.state.dropdownPos;
        if (prev && prev.top === top && prev.right === right) {
            return;
        }
        this.state.dropdownPos = { top, right };
    }

    dropdownFixedStyle() {
        const pos = this.state.dropdownPos;
        if (!pos) {
            return "";
        }
        return `position:fixed;top:${pos.top}px;right:${pos.right}px;z-index:${WhatsAppCallsSystray.DROPDOWN_Z};`;
    }

    /**
     * "Need attention" calls:
     * - still ringing / calling (incoming not handled yet in UI), or
     * - missed incoming ended calls with duration 0 (answered stays "answered")
     */
    _unansweredDomain() {
        return [
            "|",
            ["call_status", "in", ["ringing", "calling"]],
            "&",
            ["call_direction", "=", "incoming"],
            "&",
            ["call_status", "=", "ended"],
            ["duration", "=", 0],
        ];
    }

    async refreshCounts() {
        try {
            this.state.unansweredCount = await this.orm.searchCount(
                "whatsapp.call.log",
                this._unansweredDomain()
            );
        } catch (_e) {
            this.state.unansweredCount = 0;
        }
    }

    async loadDropdownItems() {
        try {
            const rows = await this.orm.searchRead(
                "whatsapp.call.log",
                this._unansweredDomain(),
                [
                    "id",
                    "from_number",
                    "partner_id",
                    "call_timestamp",
                    "call_status",
                    "call_direction",
                    "duration",
                ],
                { order: "call_timestamp desc", limit: 20 }
            );
            this.state.items = rows.map((r) => ({
                id: r.id,
                from: String((r.partner_id && r.partner_id[1]) || r.from_number || "-"),
                timestamp: r.call_timestamp || false,
                status: r.call_status,
                direction: r.call_direction,
                duration: r.duration || 0,
                label: this._rowLabel(r),
            }));
        } catch (_e) {
            this.state.items = [];
        }
    }

    _rowLabel(row) {
        if (row.call_status === "ringing" || row.call_status === "calling") {
            return "Incoming";
        }
        if (row.call_status === "ended" && row.call_direction === "incoming" && (row.duration || 0) === 0) {
            return "Missed";
        }
        if (row.call_status === "answered") {
            return "Answered";
        }
        if (row.call_status === "declined") {
            return "Declined";
        }
        return "Call";
    }

    async onClickIcon(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (this.state.open) {
            this.state.open = false;
            this.state.dropdownPos = null;
            return;
        }
        await this.refreshCounts();
        await this.loadDropdownItems();
        this._layoutDropdown();
        this.state.open = true;
    }

    onDropdownClick(ev) {
        ev.stopPropagation();
    }

    async openCallLogId(callLogId) {
        const id = Number(callLogId);
        if (!id) {
            return;
        }
        try {
            await this.action.doAction({
                type: "ir.actions.act_window",
                name: "WhatsApp Call",
                res_model: "whatsapp.call.log",
                res_id: id,
                views: [[false, "form"]],
                target: "current",
            });
            this.state.open = false;
            this.state.dropdownPos = null;
        } catch (_e) {
            this.state.open = false;
            this.state.dropdownPos = null;
        }
    }

    /**
     * List row click: QWeb-friendly handler (avoid arrow/closure in t-foreach).
     */
    async onRowClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const raw = ev.currentTarget?.dataset?.callLogId;
        await this.openCallLogId(raw);
    }

    async onViewAll(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        try {
            await this.action.doAction("comm_whatsapp_calling.action_whatsapp_call_log");
        } catch (_e) {
            // ignore
        }
        this.state.open = false;
        this.state.dropdownPos = null;
    }
}

export const whatsAppCallsSystrayItem = {
    Component: WhatsAppCallsSystray,
};

registry.category("systray").add("comm_whatsapp_calling.WhatsAppCallsSystray", whatsAppCallsSystrayItem, {
    sequence: 25,
});
