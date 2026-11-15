/** @odoo-module **/

import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { dueText } from "./queue";

const WS = "contact.centre.workspace";

/** The Team queues section, for team leads: everyone's calls, and who gets which. */
export class ContactCentreTeam extends Component {
    static template = "contact_centre_workspace.Team";
    static props = {
        boot: Object,
        setPane: Function,
        onCounts: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.bus = useService("bus_service");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            selected: false,      // an agent's id, or false for the calls nobody has
            checked: {},          // { call id: true }
            giveTo: "",
            busy: false,
        });
        this.dueText = dueText;
        this.refresh = useDebounced(() => this.load(), 500);
        this.bus.subscribe("contact_centre_queue", this.refresh);
        const tick = setInterval(() => this.load(), 60000);
        onWillDestroy(() => {
            this.bus.unsubscribe("contact_centre_queue", this.refresh);
            clearInterval(tick);
        });
        onWillStart(() => this.load());
    }

    async load() {
        const data = await this.orm.call(WS, "ws_team", [], { user_id: this.state.selected });
        this.state.data = data;
        // Calls that have left the list cannot stay ticked.
        const shown = new Set(data.rows.map((row) => row.id));
        for (const id of Object.keys(this.state.checked)) {
            if (!shown.has(parseInt(id, 10))) {
                delete this.state.checked[id];
            }
        }
        this.props.onCounts();
    }

    // ── People ───────────────────────────────────────────────────────────
    async pick(person) {
        this.state.selected = person.id;
        this.state.checked = {};
        this.props.setPane("thread");
        await this.load();
    }

    get person() {
        return this.state.data.people.find((p) => p.id === this.state.selected) || this.state.data.people[0];
    }

    stateText(person) {
        return { none: _t("Needs an agent"), ready: _t("Ready"), call: _t("On a call"), away: _t("Not ready") }[person.state];
    }

    get headline() {
        const person = this.person;
        const calls = person.todo === 1 ? _t("1 call") : _t("%s calls", person.todo);
        const what = person.id ? _t("%s to make", calls) : _t("%s waiting for an agent", calls);
        return person.late ? _t("%(what)s · %(late)s overdue", { what, late: person.late }) : what;
    }

    percent(person) {
        return person.total ? Math.round((100 * person.done) / person.total) : 0;
    }

    // ── Assigning ────────────────────────────────────────────────────────
    get checkedIds() {
        return Object.keys(this.state.checked).map((id) => parseInt(id, 10));
    }

    get allChecked() {
        const rows = this.state.data.rows;
        return rows.length > 0 && rows.every((row) => this.state.checked[row.id]);
    }

    toggle(row) {
        if (this.state.checked[row.id]) {
            delete this.state.checked[row.id];
        } else {
            this.state.checked[row.id] = true;
        }
    }

    toggleAll() {
        const all = this.allChecked;
        this.state.checked = {};
        if (!all) {
            for (const row of this.state.data.rows) {
                this.state.checked[row.id] = true;
            }
        }
    }

    async assign(ids, userId) {
        if (!ids.length || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            await this.orm.call(WS, "ws_team_assign", [ids, userId || false]);
        } finally {
            this.state.busy = false;
        }
        this.state.checked = {};
        await this.load();
    }

    assignChecked() {
        this.assign(this.checkedIds, parseInt(this.state.giveTo, 10) || false);
    }

    onRowAgent(row, ev) {
        this.assign([row.id], parseInt(ev.target.value, 10) || false);
    }

    async shareOut() {
        const shared = await this.orm.call(WS, "ws_team_share", []);
        this.notification.add(
            shared === 1 ? _t("1 call shared out.") : shared ? _t("%s calls shared out.", shared) : _t("There was nobody to share them with."),
            { type: shared ? "success" : "warning" });
        await this.load();
    }

    // ── Settings ─────────────────────────────────────────────────────────
    async onRule(ev) {
        await this.orm.call(WS, "ws_team_rule", [ev.target.value]);
        await this.load();
    }

    openCampaign(campaign) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "comm.dialer.campaign", res_id: campaign.id,
            views: [[false, "form"]], target: "current",
        });
    }

    showList() {
        this.props.setPane("list");
    }
}
