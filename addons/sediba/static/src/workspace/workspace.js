/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const WS = "sediba.workspace";
const PAGE = 40;

const STATUS_LABELS = {
    lead: _t("Lead, not verified"),
    verified: _t("Verified"),
    unconfirmed: _t("Could not confirm"),
};
const EMPTY_COLUMN = {
    lead: _t("No leads on this topic."),
    verified: _t("Nothing verified yet. A lead moves here once a source proves it."),
    unconfirmed: _t("Nothing here yet. A lead moves here when someone looked for a source and found none."),
};
const PILLS = [
    ["all", _t("All")],
    ["review", _t("To review")],
    ["verified", _t("Verified")],
    ["lead", _t("Leads")],
    ["unconfirmed", _t("Could not confirm")],
];

/**
 * The Sediba workspace: the topics down the side, and one page at a time
 * beside them (overview, a topic with its findings, one finding, the list of
 * findings, the runs). It reads through sediba.workspace; changing a record
 * opens that record's own form.
 */
export class SedibaWorkspace extends Component {
    static template = "sediba.Workspace";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        // Opened from inside another app: only that app's topics show.
        this.space = (this.props.action.params || {}).space || false;
        this.pills = PILLS;
        this.statusLabels = STATUS_LABELS;
        this.emptyColumn = EMPTY_COLUMN;
        this.state = useState({
            view: "overview", // overview | topic | finding | list | runs
            nav: { topics: [], all: 0, review: 0, runs: 0, space: false, can_edit: false },
            data: null,
            topicId: false,
            findingId: false,
            pill: "all",
            search: "", // the sidebar search, across all findings
            topicSearch: "", // the search inside one topic
            board: true, // a topic's findings as a board, or as a list
            loading: true,
            browsing: false, // phone: the sidebar is open
        });
        this.searchSoon = useDebounced(() => this.openList(this.state.search ? "all" : this.state.pill), 350);
        this.topicSearchSoon = useDebounced(() => this.load(), 350);
        onWillStart(async () => {
            const params = this.props.action.params || {};
            if (params.finding_id) {
                this.state.view = "finding";
                this.state.findingId = params.finding_id;
            } else if (params.topic_id) {
                this.state.view = "topic";
                this.state.topicId = params.topic_id;
            }
            await this.load();
        });
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    async load() {
        const s = this.state;
        s.loading = true;
        const calls = {
            overview: ["ws_overview", [this.space]],
            topic: ["ws_topic", [s.topicId, s.topicSearch, this.space]],
            finding: ["ws_finding", [s.findingId, this.space]],
            list: ["ws_findings", [s.pill, s.search, 0, PAGE, this.space]],
            runs: ["ws_runs", [0, PAGE, this.space]],
        };
        const [method, args] = calls[s.view];
        const [nav, data] = await Promise.all([this.orm.call(WS, "ws_nav", [this.space]), this.orm.call(WS, method, args)]);
        s.nav = nav;
        if (data === false) {
            // The record is gone: fall back to the overview.
            this.notification.add(_t("That record no longer exists."), { type: "warning" });
            s.view = "overview";
            s.data = await this.orm.call(WS, "ws_overview", [this.space]);
        } else {
            s.data = data;
        }
        s.loading = false;
    }

    async more() {
        const s = this.state;
        const [method, args] =
            s.view === "runs"
                ? ["ws_runs", [s.data.rows.length, PAGE, this.space]]
                : ["ws_findings", [s.pill, s.search, s.data.rows.length, PAGE, this.space]];
        const next = await this.orm.call(WS, method, args);
        s.data.rows.push(...next.rows);
        s.data.total = next.total;
    }

    // ── Moving around ────────────────────────────────────────────────────────

    go(view, extra = {}) {
        Object.assign(this.state, { view, browsing: false, data: null }, extra);
        return this.load();
    }

    openOverview() {
        return this.go("overview");
    }

    openTopic(id) {
        return this.go("topic", { topicId: id, topicSearch: "" });
    }

    openFinding(id) {
        return this.go("finding", { findingId: id });
    }

    openList(pill) {
        return this.go("list", { pill });
    }

    openRuns() {
        return this.go("runs");
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchSoon();
    }

    onTopicSearch(ev) {
        this.state.topicSearch = ev.target.value;
        this.topicSearchSoon();
    }

    isTopic(id) {
        return this.state.view === "topic" && this.state.topicId === id;
    }

    evidenceText(evidence) {
        if (!evidence.parts.length) {
            return evidence.unopened ? _t("No source opened yet") : _t("No sources yet");
        }
        return evidence.parts.map((p) => `${p.count} × ${p.label}`).join(", ");
    }

    // ── Changing things ──────────────────────────────────────────────────────

    /** Open a record's own form in a dialog, and reload when it closes. */
    form(model, id, context = {}) {
        return this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: model,
                res_id: id || false,
                views: [[false, "form"]],
                target: "new",
                context,
            },
            { onClose: () => this.load() }
        );
    }

    newFinding() {
        const topicId = this.state.view === "topic" ? this.state.topicId : false;
        return this.form("sediba.finding", false, topicId ? { default_topic_id: topicId } : {});
    }

    editTopic() {
        return this.form("sediba.topic", this.state.topicId);
    }

    editFinding() {
        return this.form("sediba.finding", this.state.findingId);
    }

    openRun(id) {
        return this.form("sediba.run", id);
    }

    async setStatus(status) {
        // The finding's own rule may refuse "verified"; Odoo shows why.
        this.state.data = await this.orm.call(WS, "ws_set_status", [this.state.findingId, status, this.space]);
        this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
    }

    async toggleReview() {
        const f = this.state.data;
        this.state.data = await this.orm.call(WS, "ws_set_review", [f.id, !f.review, this.space]);
        this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
    }
}

registry.category("actions").add("sediba_workspace", SedibaWorkspace);
