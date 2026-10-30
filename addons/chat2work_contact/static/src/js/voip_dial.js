/** @odoo-module **/

import { registry } from "@web/core/registry";

/** Start a call on the agent's softphone from the candidate form. */
function voipDial(env, action) {
    const number = ((action.params || {}).number || "").trim();
    const softphone = env.services.dialer_softphone;
    const closeAction = { type: "ir.actions.act_window_close" };
    if (!softphone) {
        env.services.notification.add("The softphone isn't ready. Reload the page and try again.", { type: "danger" });
        return closeAction;
    }
    const status = softphone.state.status;
    if (["ringing", "calling", "incall"].includes(status)) {
        env.services.notification.add("You're already on a call.", { type: "warning" });
        return closeAction;
    }
    if (status !== "registered") {
        // Opening the pad retries the connection and shows what's wrong.
        if (!softphone.state.dialerOpen) {
            softphone.toggleDialer();
        }
        env.services.notification.add("The softphone isn't connected yet. Check the pad, then try again.", { type: "warning" });
        return closeAction;
    }
    softphone.dial(number);
    env.services.orm.call("chat2work.candidate", "c2w_note_voip_call", [[action.params.candidate_id]]);
    return closeAction;
}

registry.category("actions").add("chat2work_contact.voip_dial", voipDial);
