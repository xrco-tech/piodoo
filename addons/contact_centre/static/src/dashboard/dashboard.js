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
            channels: [],
            conversationStates: { open: 0, pending: 0, resolved: 0 },
            responseTime: { avg_seconds: null, sample_size: 0 },
            customCards: [],
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

            const channelLabels = {
                whatsapp: "WhatsApp", sms: "SMS", email: "Email", voice: "Voice",
            };
            let channels = [];
            try {
                const channelGroups = await this.orm.readGroup(
                    "contact.centre.message", [], ["channel"], ["channel"]
                );
                channels = channelGroups.map((g) => ({
                    channel: g.channel,
                    label: channelLabels[g.channel] || g.channel,
                    count: g.channel_count,
                }));
            } catch (_e) {
                // Ignore — channel breakdown is a nice-to-have
            }

            let conversationStates = { open: 0, pending: 0, resolved: 0 };
            try {
                const stateGroups = await this.orm.readGroup(
                    "contact.centre.contact", [], ["state"], ["state"]
                );
                for (const g of stateGroups) {
                    if (g.state in conversationStates) {
                        conversationStates[g.state] = g.state_count;
                    }
                }
            } catch (_e) {
                // contact_centre_sync (which adds `state`) may not be installed
            }

            let responseTime = { avg_seconds: null, sample_size: 0 };
            try {
                responseTime = await this.orm.call(
                    "contact.centre.message", "get_response_time_stats", []
                );
            } catch (_e) {
                // Ignore — response time is a nice-to-have
            }

            let customCards = [];
            try {
                const cardDefs = await this.orm.searchRead(
                    "contact.centre.dashboard.card", [["active", "=", true]],
                    ["name", "model_name", "metric_type", "domain", "group_by_field", "icon", "color"],
                    { order: "sequence asc" }
                );
                customCards = await Promise.all(cardDefs.map((card) => this._loadCustomCard(card)));
            } catch (_e) {
                // contact_centre_ai_ops's dashboard-card model may not exist on older deployments
            }

            Object.assign(this.state, {
                loading: false,
                contacts: { total: totalContacts, new_this_month: newContacts },
                messages: { total: totalMessages, today: todayMessages, failed: failedMessages },
                campaigns: { total: totalCampaigns, running: runningCampaigns, done: doneCampaigns },
                chatbots: { total: totalChatbots, active: activeSessions, waiting: waitingSessions },
                channels,
                conversationStates,
                responseTime,
                customCards,
            });
        } catch (err) {
            console.error("[Contact Centre] Dashboard load error:", err);
            this.state.loading = false;
        }
    }

    // A bad card (invalid group_by_field, malformed domain, etc.) only
    // fails its own value — never breaks the rest of the dashboard load.
    async _loadCustomCard(card) {
        let value = null;
        let breakdown = [];
        try {
            const domain = card.domain || [];
            if (card.metric_type === "group_by" && card.group_by_field) {
                const groups = await this.orm.readGroup(
                    card.model_name, domain, [card.group_by_field], [card.group_by_field]
                );
                breakdown = groups.map((g) => ({
                    label: g[card.group_by_field] || "(none)",
                    count: g[`${card.group_by_field}_count`],
                }));
                value = breakdown.reduce((sum, b) => sum + b.count, 0);
            } else {
                value = await this.orm.searchCount(card.model_name, domain);
            }
        } catch (_e) {
            value = null;
        }
        return { ...card, value, breakdown };
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

    openConversationsByState(state) {
        this._doWindowAction(
            `Conversations — ${state}`, "contact.centre.contact", [["state", "=", state]]
        );
    }

    openInboundMessages() {
        this._doWindowAction("Inbound Messages", "contact.centre.message", [
            ["direction", "=", "inbound"],
        ]);
    }

    openCustomCard(card) {
        this._doWindowAction(card.name, card.model_name, card.domain || []);
    }

    formatResponseTime() {
        const seconds = this.state.responseTime.avg_seconds;
        if (seconds === null || seconds === undefined) {
            return "No data yet";
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.round(seconds % 60);
        return `${minutes}m ${remainingSeconds}s`;
    }
}

registry.category("actions").add("contact_centre_dashboard", ContactCentreDashboard);
