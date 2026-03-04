/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class ContactCentreDashboard extends Component {
    static template = "contact_centre.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            contacts: { total: 0, new_this_month: 0 },
            messages: { total: 0, today: 0, failed: 0 },
            campaigns: { total: 0, running: 0, done: 0 },
            chatbots: { total: 0, active: 0, waiting: 0 },
        });

        onWillStart(() => this._loadData());
    }

    async _loadData() {
        try {
            const now = new Date();
            const todayStr = now.toISOString().split("T")[0] + " 00:00:00";
            const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
                .toISOString()
                .split("T")[0] + " 00:00:00";

            const [
                totalContacts,
                newContacts,
                totalMessages,
                todayMessages,
                failedMessages,
                totalCampaigns,
                runningCampaigns,
                doneCampaigns,
            ] = await Promise.all([
                this.orm.searchCount("contact.centre.contact", []),
                this.orm.searchCount("contact.centre.contact", [
                    ["create_date", ">=", firstOfMonth],
                ]),
                this.orm.searchCount("contact.centre.message", []),
                this.orm.searchCount("contact.centre.message", [
                    ["message_timestamp", ">=", todayStr],
                ]),
                this.orm.searchCount("contact.centre.message", [
                    ["status", "=", "failed"],
                ]),
                this.orm.searchCount("contact.centre.campaign", []),
                this.orm.searchCount("contact.centre.campaign", [
                    ["state", "=", "running"],
                ]),
                this.orm.searchCount("contact.centre.campaign", [
                    ["state", "=", "done"],
                ]),
            ]);

            let totalChatbots = 0;
            let activeSessions = 0;
            let waitingSessions = 0;
            try {
                [totalChatbots, activeSessions, waitingSessions] = await Promise.all([
                    this.orm.searchCount("contact.centre.chatbot", []),
                    this.orm.searchCount("contact.centre.chatbot.session", [
                        ["state", "=", "active"],
                    ]),
                    this.orm.searchCount("contact.centre.chatbot.session", [
                        ["state", "=", "waiting_human"],
                    ]),
                ]);
            } catch (_e) {
                // Chatbot models may not exist or may not be installed
            }

            Object.assign(this.state, {
                loading: false,
                contacts: { total: totalContacts, new_this_month: newContacts },
                messages: { total: totalMessages, today: todayMessages, failed: failedMessages },
                campaigns: { total: totalCampaigns, running: runningCampaigns, done: doneCampaigns },
                chatbots: { total: totalChatbots, active: activeSessions, waiting: waitingSessions },
            });
        } catch (err) {
            console.error("[Contact Centre] Dashboard load error:", err);
            this.state.loading = false;
        }
    }

    // -------------------------------------------------------------------------
    // Navigation helpers
    // -------------------------------------------------------------------------

    _doAction(xmlId) {
        this.action.doAction(xmlId);
    }

    _doWindowAction(name, model, domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openContacts() {
        this._doAction("contact_centre.action_contact_centre_contact");
    }

    openMessages() {
        this._doWindowAction("Messages", "contact.centre.message");
    }

    openFailedMessages(ev) {
        ev.stopPropagation();
        this._doWindowAction("Failed Messages", "contact.centre.message", [
            ["status", "=", "failed"],
        ]);
    }

    openCampaigns() {
        this._doAction("contact_centre.action_contact_centre_campaign_overview");
    }

    openRunningCampaigns(ev) {
        ev.stopPropagation();
        this._doWindowAction("Running Campaigns", "contact.centre.campaign", [
            ["state", "=", "running"],
        ]);
    }

    openChatbots() {
        this._doAction("contact_centre.action_contact_centre_chatbot_session");
    }

    openWaitingSessions(ev) {
        ev.stopPropagation();
        this._doAction("contact_centre.action_contact_centre_chatbot_session_human");
    }
}

registry.category("actions").add("contact_centre_dashboard", ContactCentreDashboard);
