/** @odoo-module **/

/**
 * Token watchdog listener — receives `whatsapp_token_expired` bus events
 * fired by the daily cron and surfaces a sticky in-browser notification
 * so an admin gets alerted before real Meta traffic hits the expired
 * token. Registered as a service so it starts on page load without
 * needing to be embedded in a component.
 */

import { registry } from "@web/core/registry";

const tokenWatchdogService = {
    dependencies: ["bus_service", "notification"],
    start(env, { bus_service, notification }) {
        try {
            bus_service.subscribe("whatsapp_token_expired", (payload) => {
                const accs = (payload && payload.accounts) || [];
                if (!accs.length) return;
                const names = accs.map(a => a.name).join(", ");
                const detail = accs.map(a =>
                    `• ${a.name}${a.error ? ` — ${a.error}` : ""}`
                ).join("\n");
                notification.add(
                    `WhatsApp token expired: ${names}\n\n${detail}\n\n` +
                    "Refresh from Meta Business Manager, then paste the " +
                    "new token onto the account.",
                    { type: "danger", sticky: true, title: "Token expired" }
                );
            });
            if (typeof bus_service.start === "function") {
                bus_service.start();
            }
        } catch (e) {
            console.warn("[wa-token-watchdog] subscribe failed:", e);
        }
        return {};
    },
};

registry.category("services").add("comm_whatsapp.token_watchdog", tokenWatchdogService);
