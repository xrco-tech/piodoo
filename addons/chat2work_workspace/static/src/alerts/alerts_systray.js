/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SHOWN = 6;

/** The Chat2Work icon in the top bar: how many people are waiting, and the alert settings. */
export class Chat2workAlertsSystray extends Component {
    static template = "chat2work_workspace.AlertsSystray";
    static components = { Dropdown, DropdownItem };
    static props = {};

    setup() {
        this.alerts = useService("chat2work_alerts");
        this.state = useState(this.alerts.state);
    }

    get badge() {
        return this.state.count > 99 ? "99+" : this.state.count;
    }

    get lists() {
        const counts = this.state.counts;
        return [
            { pill: "reply", label: _t("Waiting for a reply"), count: counts.reply },
            { pill: "callbacks", label: _t("Callbacks"), count: counts.callback },
            { pill: "unknown", label: _t("Not candidates yet"), count: counts.unknown },
        ];
    }

    get recent() {
        return this.state.items.slice(0, SHOWN);
    }

    get desktopLabel() {
        return {
            granted: _t("On"),
            denied: _t("Blocked in this browser's site settings"),
            default: _t("Turn on"),
        }[this.state.desktop];
    }

    when(value) {
        const dt = deserializeDateTime(value);
        return dt.hasSame(luxon.DateTime.local(), "day") ? dt.toFormat("HH:mm") : dt.toFormat("d MMM HH:mm");
    }

    openList(pill) {
        return this.alerts.open({ pill });
    }

    openItem(item) {
        return this.alerts.open(this.alerts.targetOf(item));
    }

    toggleSound() {
        this.alerts.setSound(!this.state.sound);
    }
}

registry.category("systray").add("chat2work_workspace.alerts", { Component: Chat2workAlertsSystray }, { sequence: 30 });
