/** @odoo-module **/

/**
 * Client action `comm_whatsapp_calling.dial` — bridge between the
 * server-side action_whatsapp_call button on res.partner and the OWL
 * calling service registered in incoming_call_popup.js. Reads the
 * to_number / partner_id / partner_name from the action params and
 * kicks off dialCall().
 */

import { registry } from "@web/core/registry";

// Odoo 18 client-action factories are called as fn(env, action) — two
// positional arguments, not a destructured object.
async function dialFromAction(env, action) {
    const params = (action && action.params) || {};
    const to = (params.to_number || "").trim();
    if (!to) {
        env.services.notification.add(
            "This partner has no phone number.", { type: "warning" });
        return { type: "ir.actions.act_window_close" };
    }
    const svc = env.services.comm_whatsapp_calling;
    if (!svc || typeof svc.dialCall !== "function") {
        env.services.notification.add(
            "Calling service not ready — reload the page and retry.",
            { type: "danger" });
        return { type: "ir.actions.act_window_close" };
    }
    await svc.dialCall({
        toNumber:    to,
        partnerId:   params.partner_id || null,
        partnerName: params.partner_name || to,
    });
    return { type: "ir.actions.act_window_close" };
}

registry.category("actions").add("comm_whatsapp_calling.dial", dialFromAction);
