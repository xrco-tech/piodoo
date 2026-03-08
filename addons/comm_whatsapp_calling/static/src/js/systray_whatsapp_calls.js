/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WhatsAppCallsSystray extends Component {
    static template = "comm_whatsapp_calling.WhatsAppCallsSystray";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ unansweredCount: 0 });

        onWillStart(async () => {
            await this.loadUnansweredCount();
        });
    }

    async loadUnansweredCount() {
        try {
            const count = await this.orm.searchCount(
                "whatsapp.call.log",
                [["call_status", "in", ["ringing", "calling"]]]
            );
            this.state.unansweredCount = count;
        } catch (_e) {
            this.state.unansweredCount = 0;
        }
    }

    async onClick() {
        await this.loadUnansweredCount();
        await this.action.doAction("comm_whatsapp_calling.action_whatsapp_call_log");
    }
}

export const whatsAppCallsSystrayItem = {
    Component: WhatsAppCallsSystray,
};

registry.category("systray").add("comm_whatsapp_calling.WhatsAppCallsSystray", whatsAppCallsSystrayItem, {
    sequence: 25,
});
