/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { when } from "./util";

const WS = "contact.centre.workspace";
const CAMPAIGN = "contact.centre.campaign";
const PAGE = 40;
const BADGE = { whatsapp: "WA", sms: "SMS", voice: "Tel", email: "@", both: "WA" };
const ICON = { whatsapp: "fa-whatsapp", sms: "fa-commenting-o", email: "fa-envelope-o", both: "fa-comments-o" };

/** The Campaigns section: the campaigns, and one campaign beside the list. */
export class ContactCentreCampaigns extends Component {
    static template = "contact_centre_workspace.Campaigns";
    static props = {
        boot: Object,
        openId: { type: [Number, Boolean], optional: true },
        setPane: Function,
        openConversation: Function,
        openCampaignInbox: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            pill: "all",
            search: "",
            rows: [],
            total: 0,
            more: false,
            canManage: false,
            loading: true,
            sel: false,
            campaign: null,
            loadingCampaign: false,
            infoOpen: true,
            confirm: false,        // the action waiting for a second click
            working: false,
            error: "",
        });
        this.when = when;
        this.searchLater = useDebounced(() => this.loadList(), 300);
        onWillStart(async () => {
            await this.loadList();
            if (this.props.openId) {
                await this.open(this.props.openId);
            }
        });
    }

    // ── Loading ──────────────────────────────────────────────────────────
    async loadList(limit = PAGE) {
        this.state.loading = true;
        try {
            const result = await this.orm.call(WS, "ws_campaigns", [], {
                pill: this.state.pill, search: this.state.search, offset: 0, limit,
            });
            this.state.rows = result.rows;
            this.state.total = result.total;
            this.state.more = result.more;
            this.state.canManage = result.can_manage;
        } finally {
            this.state.loading = false;
        }
    }

    async loadMore() {
        const result = await this.orm.call(WS, "ws_campaigns", [], {
            pill: this.state.pill, search: this.state.search, offset: this.state.rows.length, limit: PAGE,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async open(id) {
        this.state.sel = id;
        this.state.confirm = false;
        this.state.error = "";
        this.props.setPane("thread");
        this.state.loadingCampaign = !this.state.campaign;
        try {
            const campaign = await this.orm.call(WS, "ws_campaign", [id]);
            if (this.state.sel === id) {
                this.state.campaign = campaign;
            }
        } finally {
            this.state.loadingCampaign = false;
        }
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        return [
            { key: "all", label: _t("All") },
            { key: "running", label: _t("Running") },
            { key: "draft", label: _t("Draft") },
            { key: "done", label: _t("Done") },
            { key: "cancelled", label: _t("Cancelled") },
            { key: "outbound", label: _t("Outbound") },
            { key: "inbound", label: _t("Inbound") },
        ];
    }

    setPill(key) {
        this.state.pill = key;
        this.loadList();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchLater();
    }

    icon(channel) {
        return ICON[channel] || "fa-bullhorn";
    }

    badge(channel) {
        return BADGE[channel] || "";
    }

    stateClass(state) {
        return { running: "ok", draft: "plain", done: "plain", cancelled: "warn" }[state] || "plain";
    }

    /** "WhatsApp · 42 contacts": the arrow beside it says outbound or inbound. */
    line(row) {
        const people = row.contacts === 1 ? _t("1 contact") : _t("%s contacts", row.contacts);
        return [row.channel_label, people].join(" · ");
    }

    get totalText() {
        const total = this.state.total;
        return total === 1 ? _t("1 campaign") : _t("%s campaigns", total);
    }

    // ── One campaign ─────────────────────────────────────────────────────
    full(value) {
        return value ? deserializeDateTime(value).toFormat("d MMM yyyy, HH:mm") : "";
    }

    statusClass(status) {
        return { failed: "warn", delivered: "ok", read: "ok" }[status] || "plain";
    }

    get progressWidth() {
        const progress = this.state.campaign.progress;
        return `${Math.round((100 * progress.done) / Math.max(1, progress.total))}%`;
    }

    get facts() {
        const campaign = this.state.campaign;
        return [
            { label: _t("Type"), value: campaign.type_label },
            { label: _t("Channel"), value: campaign.channel_label },
            { label: _t("Agent script"), value: campaign.script },
            { label: _t("Call script"), value: campaign.voice_script },
            { label: _t("Started"), value: this.full(campaign.started) },
            { label: _t("Ended"), value: this.full(campaign.ended) },
        ].filter((d) => d.value);
    }

    openInbox() {
        const campaign = this.state.campaign;
        this.props.openCampaignInbox(campaign.id, campaign.name);
    }

    /** The campaign's form: where it is built and changed. */
    openRecord() {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: CAMPAIGN, res_id: this.state.campaign.id, views: [[false, "form"]],
        });
    }

    newCampaign() {
        this.action.doAction({ type: "ir.actions.act_window", res_model: CAMPAIGN, views: [[false, "form"]] });
    }

    // ── Starting and stopping ────────────────────────────────────────────
    actionLabel(action) {
        return {
            start: _t("Start campaign"), done: _t("Mark as done"), cancel: _t("Cancel campaign"), reset: _t("Reset to draft"),
        }[action];
    }

    /** What the second click will do, said plainly before it happens. */
    get confirmText() {
        const campaign = this.state.campaign;
        const people = campaign.stats[0].value === 1 ? _t("1 contact") : _t("%s contacts", campaign.stats[0].value);
        switch (this.state.confirm) {
            case "start":
                return campaign.outbound
                    ? _t("This starts sending “%(template)s” to %(people)s on %(channel)s. Messages that have gone out cannot be taken back.", {
                          template: campaign.template ? campaign.template.name : _t("no template"), people, channel: campaign.channel_label })
                    : _t("This opens the campaign: its automated replies start answering.");
            case "done":
                return campaign.outbound
                    ? _t("This ends the campaign. Contacts who have not been sent the message yet will not get it.")
                    : _t("This ends the campaign.");
            case "cancel":
                return _t("This cancels the campaign. Nothing more is sent.");
            default:
                return _t("This puts the campaign back to draft and clears its progress, so starting it again sends to everyone again.");
        }
    }

    ask(action) {
        this.state.error = "";
        this.state.confirm = action;
    }

    back() {
        this.state.confirm = false;
    }

    async run() {
        const action = this.state.confirm;
        if (!action || this.state.working) {
            return;
        }
        this.state.working = true;
        this.state.error = "";
        try {
            this.state.campaign = await this.orm.silent.call(WS, "ws_campaign_action", [this.state.sel, action]);
            this.state.confirm = false;
            await this.loadList(Math.max(PAGE, this.state.rows.length));
        } catch (error) {
            // Why it could not start (no template, no contacts) goes beside the button.
            this.state.confirm = false;
            this.state.error = (error && error.data && error.data.message) || _t("That did not work.");
        } finally {
            this.state.working = false;
        }
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    showCampaign() {
        this.props.setPane("thread");
    }

    /** On a phone the card is a pane of its own; on a wide screen it opens and closes. */
    toggleInfo() {
        if (this.env.isSmall) {
            this.state.infoOpen = true;
            this.props.setPane("info");
        } else {
            this.state.infoOpen = !this.state.infoOpen;
        }
    }
}
