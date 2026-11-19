/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { formatCurrency } from "@web/core/currency";
import { formatFloat } from "@web/core/utils/numbers";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REPORT = "comm.billing.report";

/** Comm Billing reports: spend overview with the budget, and the monthly statement. */
export class CommBillingReports extends Component {
    static template = "comm_billing_core.Reports";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            view: "overview",
            period: "month",
            dateFrom: "",
            dateTo: "",
            pickingDates: false,
            groupBy: "category",
            source: "",
            data: null,
            statement: null,
            loading: true,
            error: "",
        });
        // Another app's dashboard can open the reports on its own spend and dates.
        const params = this.props.action.params || {};
        if (params.source) {
            this.state.source = params.source;
        }
        if (params.date_from && params.date_to) {
            this.state.period = "custom";
            this.state.dateFrom = params.date_from;
            this.state.dateTo = params.date_to;
        }
        onWillStart(() => this.load());
    }

    // ---- loading ----------------------------------------------------
    async run(call) {
        this.state.loading = true;
        this.state.error = "";
        try {
            await call();
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || _t("The report could not be loaded.");
        } finally {
            this.state.loading = false;
        }
    }

    load() {
        const { period, dateFrom, dateTo, groupBy, source } = this.state;
        return this.run(async () => {
            this.state.data = await this.orm.call(REPORT, "overview", [], {
                period,
                date_from: dateFrom || false,
                date_to: dateTo || false,
                group_by: groupBy,
                source: source || false,
            });
        });
    }

    loadStatement(month) {
        return this.run(async () => {
            this.state.statement = await this.orm.call(REPORT, "statement", [month || false]);
        });
    }

    // ---- overview controls -----------------------------------------
    get periods() {
        return [
            { key: "month", label: _t("This month") },
            { key: "last_month", label: _t("Last month") },
            { key: "3m", label: _t("Last 3 months") },
        ];
    }

    get groups() {
        return [
            { key: "category", label: _t("Type of charge") },
            { key: "source", label: _t("Caused by") },
            { key: "campaign", label: _t("Campaign") },
            { key: "account", label: _t("Our number") },
            { key: "country", label: _t("Country") },
            { key: "contact", label: _t("Contact") },
        ];
    }

    get groupLabel() {
        return this.groups.find((g) => g.key === this.state.groupBy).label;
    }

    setPeriod(period) {
        this.state.pickingDates = false;
        if (period !== this.state.period) {
            this.state.period = period;
            this.load();
        }
    }

    toggleDates() {
        this.state.pickingDates = !this.state.pickingDates;
        if (this.state.pickingDates && !this.state.dateFrom && this.state.data) {
            this.state.dateFrom = this.state.data.date_from;
            this.state.dateTo = this.state.data.date_to;
        }
    }

    applyDates() {
        if (this.state.dateFrom && this.state.dateTo) {
            this.state.period = "custom";
            this.load();
        }
    }

    setSource(source) {
        if (source !== this.state.source) {
            this.state.source = source;
            this.load();
        }
    }

    setGroup(group) {
        if (group !== this.state.groupBy) {
            this.state.groupBy = group;
            this.load();
        }
    }

    // ---- wording ----------------------------------------------------
    money(amount, digits) {
        const data = this.state.view === "statement" ? this.state.statement : this.state.data;
        return formatCurrency(amount || 0, data.currency_id, digits === undefined ? {} : { digits: [16, digits] });
    }

    /** Whole currency units for the big tiles. */
    round(amount) {
        return this.money(Math.round(amount || 0), 0);
    }

    qty(value) {
        return formatFloat(value || 0, { digits: [16, Number.isInteger(value) ? 0 : 1] });
    }

    rate(value) {
        return this.money(value, value < 1 ? 4 : 2);
    }

    get fixedText() {
        const fees = this.state.data.fees;
        if (!fees.length) {
            return _t("None charged in this period");
        }
        const sum = (kind) => fees.filter((fee) => fee.kind === kind).reduce((total, fee) => total + fee.cost, 0);
        const parts = [];
        if (sum("monthly")) {
            parts.push(_t("%s monthly", this.money(sum("monthly"))));
        }
        if (sum("once")) {
            parts.push(_t("%s once", this.money(sum("once"))));
        }
        return parts.join(", ");
    }

    get changeText() {
        const { change_pct: pct, prev_span: span } = this.state.data;
        if (pct === null) {
            return _t("Nothing was spent in %s to compare with", span);
        }
        if (pct === 0) {
            return _t("The same as %s", span);
        }
        return pct > 0
            ? _t("%(pct)s% more than %(span)s", { pct, span })
            : _t("%(pct)s% less than %(span)s", { pct: -pct, span });
    }

    channelNote(channel) {
        const parts = [];
        if (channel.limit) {
            parts.push(_t("%(pct)s% of its %(limit)s limit used", {
                pct: channel.limit_pct,
                limit: this.round(channel.limit),
            }));
        }
        const change = Math.round(channel.change);
        if (change > 0) {
            parts.push(_t("%s more than the period before", this.round(change)));
        } else if (change < 0) {
            parts.push(_t("%s less than the period before", this.round(-change)));
        } else {
            parts.push(_t("About the same as the period before"));
        }
        return parts.join(". ");
    }

    channelNoteClass(channel) {
        if (channel.limit && channel.limit_pct > 100) {
            return "text-danger";
        }
        return Math.round(channel.change) > 0 ? "text-danger" : Math.round(channel.change) < 0 ? "text-success" : "text-muted";
    }

    get budgetVerdict() {
        const budget = this.state.data.budget;
        const over = Math.round(budget.over);
        if (budget.current) {
            return over > 0
                ? { text: _t("Likely to end %s over", this.round(over)), over: true }
                : { text: _t("On course to end %s under", this.round(-over)), over: false };
        }
        return over > 0
            ? { text: _t("Ended %s over", this.round(over)), over: true }
            : { text: _t("Ended %s under", this.round(-over)), over: false };
    }

    get peak() {
        return this.state.data.days.bars.find((bar) => bar.peak);
    }

    checkLabel(check) {
        return {
            match: _t("Matches"),
            close: _t("Close enough"),
            differs: _t("Does not match"),
            missing: _t("Invoice needed"),
        }[check.result];
    }

    checkClass(check) {
        return { match: "text-success", close: "text-success", differs: "text-danger", missing: "text-warning" }[check.result];
    }

    // ---- going elsewhere --------------------------------------------
    openEvents(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "comm.billing.event",
            views: [[false, "list"], [false, "pivot"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    openChannel(channel) {
        this.openEvents(channel.label, [...this.state.data.domain, ["channel", "=", channel.key]]);
    }

    openRow(row) {
        this.openEvents(row.label, row.domain);
    }

    openDay(bar) {
        this.openEvents(bar.label, bar.domain);
    }

    openUnpriced() {
        const data = this.state.view === "statement" ? this.state.statement : this.state.data;
        this.openEvents(_t("Charges with no matching rate"), [...data.domain, ["rate_id", "=", false], ["fee_id", "=", false], ["is_free", "=", false]]);
    }

    openBudget() {
        this.action.doAction("comm_billing_core.action_comm_billing_budget");
    }

    openFees() {
        this.action.doAction("comm_billing_core.action_comm_billing_fee");
    }

    openInvoices() {
        this.action.doAction("comm_billing_core.action_comm_billing_invoice");
    }

    // ---- statement --------------------------------------------------
    showStatement() {
        this.state.view = "statement";
        const data = this.state.data;
        // Open on the month being looked at, when it is a single month.
        const month = data && ["month", "last_month"].includes(data.period) ? data.date_from.slice(0, 7) : false;
        return this.loadStatement(month);
    }

    showOverview() {
        this.state.view = "overview";
    }

    setMonth(ev) {
        if (ev.target.value) {
            this.loadStatement(ev.target.value);
        }
    }

    downloadStatement() {
        this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "comm_billing_core.report_statement",
            report_file: "comm_billing_core.report_statement",
            data: { month: this.state.statement.month },
            context: { active_model: "comm.billing.budget" },
        });
    }
}

registry.category("actions").add("comm_billing_core.reports", CommBillingReports);
