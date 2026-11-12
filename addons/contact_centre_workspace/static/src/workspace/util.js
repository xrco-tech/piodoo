/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";

const { DateTime } = luxon;

/** A short "when" for a list row: the time today, "Yesterday", else the date. */
export function when(value) {
    if (!value) {
        return "";
    }
    const dt = deserializeDateTime(value);
    const now = DateTime.local();
    if (dt.hasSame(now, "day")) {
        return dt.toFormat("HH:mm");
    }
    if (dt.hasSame(now.minus({ days: 1 }), "day")) {
        return _t("Yesterday");
    }
    return dt.toFormat(dt.hasSame(now, "year") ? "d MMM" : "d MMM yyyy");
}

/** WhatsApp call through the phone card, with a script to follow when one is given. */
export function dialWhatsApp(services, { phone, name, partnerId, bot }) {
    const calling = services.comm_whatsapp_calling;
    if (!phone) {
        services.notification.add(_t("This contact has no phone number."), { type: "warning" });
        return;
    }
    if (!calling) {
        services.notification.add(_t("WhatsApp calling isn't available."), { type: "danger" });
        return;
    }
    calling.dialCall({
        toNumber: phone,
        partnerId: partnerId || undefined,
        partnerName: name,
        chatbotId: bot ? bot.id : undefined,
        chatbotName: bot ? bot.name : undefined,
    });
}

/** VoIP call through the agent's own softphone. */
export function dialVoip(services, phone) {
    const softphone = services.dialer_softphone;
    if (!softphone || !phone) {
        services.notification.add(_t("The softphone isn't ready, or this contact has no phone number."), { type: "warning" });
        return;
    }
    const status = softphone.state.status;
    if (["ringing", "calling", "incall"].includes(status)) {
        services.notification.add(_t("You're already on a call."), { type: "warning" });
        return;
    }
    if (status !== "registered") {
        // Opening the pad retries the connection and shows what's wrong.
        if (!softphone.state.dialerOpen) {
            softphone.toggleDialer();
        }
        services.notification.add(_t("The softphone isn't connected yet. Check the pad, then try again."), { type: "warning" });
        return;
    }
    softphone.dial(phone);
}
