/** @odoo-module **/
// UCX efficiency dashboard — one component, three role scopes.
// Scope ('me' | 'team' | 'org') comes from the client action's context.
// Reads everything from cx.dashboard.get_metrics; renders KPI cards, a trend,
// a first-response distribution, a sentiment donut and (team/org) a leaderboard.
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const DAY_OPTIONS = [7, 30, 90];

export class CxDashboard extends Component {
    static template = "cx_module.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const ctx = (this.props.action && this.props.action.context) || {};
        this.state = useState({
            scope: ctx.dashboard_scope || "me",
            rangeMode: "days",         // "days" | "custom"
            days: 30,
            dateFrom: "",
            dateTo: "",
            filters: { teams: [], agents: [], channels: [], campaigns: [], direction: "" },
            openFilter: null,          // which filter dropdown panel is open
            loading: true,
            data: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            const kwargs = {
                scope: this.state.scope,
                days: this.state.days,
                filters: JSON.parse(JSON.stringify(this.state.filters)),
            };
            if (this.state.rangeMode === "custom" && this.state.dateFrom && this.state.dateTo) {
                kwargs.date_from = this.state.dateFrom;
                kwargs.date_to = this.state.dateTo;
            }
            this.state.data = await this.orm.call("cx.dashboard", "get_metrics", [], kwargs);
        } finally {
            this.state.loading = false;
        }
    }

    get dayOptions() {
        return DAY_OPTIONS;
    }

    setDays(d) {
        this.state.rangeMode = "days";
        this.state.days = d;
        this.state.dateFrom = "";
        this.state.dateTo = "";
        this.load();
    }

    onDateFrom(ev) { this.state.dateFrom = ev.target.value; }
    onDateTo(ev) { this.state.dateTo = ev.target.value; }

    applyCustomRange() {
        if (this.state.dateFrom && this.state.dateTo) {
            this.state.rangeMode = "custom";
            this.load();
        }
    }

    // ------------------------------------------------------------------ filters
    // Which filter dimensions apply to this scope (direction is rendered separately).
    get filterDims() {
        const o = (this.state.data && this.state.data.filter_options) || {};
        const scope = this.state.scope;
        const dims = [];
        if (scope === "org") {
            dims.push({ key: "teams", label: "Teams",
                        options: (o.teams || []).map((t) => ({ id: t, name: t })) });
        }
        if (scope !== "me") {
            dims.push({ key: "agents", label: "Agents", options: o.agents || [] });
        }
        dims.push({ key: "channels", label: "Channels", options: o.channels || [] });
        dims.push({ key: "campaigns", label: "Campaigns", options: o.campaigns || [] });
        return dims;
    }

    filterLabel(dim) {
        const n = this.state.filters[dim.key].length;
        return n ? `${dim.label}: ${n}` : `${dim.label}: All`;
    }

    isChecked(key, id) {
        return this.state.filters[key].includes(id);
    }

    toggleFilter(key, id) {
        const arr = this.state.filters[key];
        const i = arr.indexOf(id);
        if (i >= 0) { arr.splice(i, 1); } else { arr.push(id); }
        this.load();
    }

    clearFilter(key) {
        this.state.filters[key] = [];
        this.load();
    }

    togglePanel(key) {
        this.state.openFilter = this.state.openFilter === key ? null : key;
    }

    setDirection(d) {
        this.state.filters.direction = d;
        this.load();
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return f.teams.length || f.agents.length || f.channels.length ||
               f.campaigns.length || f.direction;
    }

    clearAllFilters() {
        this.state.filters = { teams: [], agents: [], channels: [], campaigns: [], direction: "" };
        this.state.openFilter = null;
        this.load();
    }

    // -------------------------------------------------------------- formatting
    fmtDuration(secs) {
        if (secs === null || secs === undefined) return "—";
        secs = Math.round(secs);
        if (secs < 60) return `${secs}s`;
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        if (m < 60) return `${m}m ${String(s).padStart(2, "0")}s`;
        const h = Math.floor(m / 60);
        return `${h}h ${String(m % 60).padStart(2, "0")}m`;
    }

    fmtPct(v) {
        return v === null || v === undefined ? "—" : `${v}%`;
    }

    fmtNum(v) {
        return (v || 0).toLocaleString();
    }

    fmtMoney(v) {
        const c = this.state.data && this.state.data.currency;
        const sym = (c && c.symbol) || "$";
        const amt = Number(v || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return c && c.position === "after" ? `${amt} ${sym}` : `${sym}${amt}`;
    }

    titleCase(s) {
        return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
    }

    // -------------------------------------------------------- omni-channel (org)
    get omni() {
        return (this.state.data && this.state.data.omni) || null;
    }

    // Channel mix rows scaled to the busiest channel (by conversations).
    get channelBars() {
        const ch = (this.omni && this.omni.channels) || [];
        const max = Math.max(1, ...ch.map((r) => r.conversations));
        return ch.map((r) => ({ ...r, w: (100 * r.conversations) / max }));
    }

    get campaignChannelBars() {
        const bc = (this.omni && this.omni.campaigns.by_channel) || [];
        const max = Math.max(1, ...bc.map((r) => r.sends));
        return bc.map((r) => ({ ...r, w: (100 * r.sends) / max }));
    }

    // ------------------------------------------------------------------- trend
    // Return the trend as {bars:[{x,label,openedH,closedH}], max} in a 0..100 box.
    get trendBars() {
        const t = (this.state.data && this.state.data.trend) || [];
        const max = Math.max(1, ...t.map((r) => Math.max(r.opened, r.closed)));
        return {
            max,
            bars: t.map((r) => ({
                label: r.day.slice(5), // MM-DD
                opened: r.opened,
                closed: r.closed,
                openedH: (100 * r.opened) / max,
                closedH: (100 * r.closed) / max,
            })),
        };
    }

    get dowBars() {
        const d = (this.state.data && this.state.data.dow) || [];
        const max = Math.max(1, ...d.map((r) => r.opened));
        return d.map((r) => ({ ...r, h: (100 * r.opened) / max }));
    }

    get distribution() {
        const d = (this.state.data && this.state.data.fr_distribution) || [];
        const max = Math.max(1, ...d.map((r) => r.count));
        return d.map((r) => ({ ...r, w: (100 * r.count) / max }));
    }

    // ---------------------------------------------------------------- sentiment
    // Build donut arc segments (positive/neutral/negative/unrated) as SVG paths.
    get sentimentDonut() {
        const s = (this.state.data && this.state.data.sentiment) || {};
        const parts = [
            { key: "positive", label: "Positive", value: s.positive || 0, color: "#28a745" },
            { key: "neutral", label: "Neutral", value: s.neutral || 0, color: "#f0ad4e" },
            { key: "negative", label: "Negative", value: s.negative || 0, color: "#dc3545" },
            { key: "unrated", label: "Unrated", value: s.unrated || 0, color: "#c7ccd1" },
        ];
        const total = parts.reduce((a, p) => a + p.value, 0) || 1;
        let angle = -Math.PI / 2;
        const R = 52;
        const r = 32;
        const cx = 60;
        const cy = 60;
        const segs = [];
        for (const p of parts) {
            if (!p.value) {
                segs.push({ ...p, path: "", pct: 0 });
                continue;
            }
            const frac = p.value / total;
            const a0 = angle;
            const a1 = angle + frac * 2 * Math.PI;
            angle = a1;
            const large = a1 - a0 > Math.PI ? 1 : 0;
            const x0o = cx + R * Math.cos(a0), y0o = cy + R * Math.sin(a0);
            const x1o = cx + R * Math.cos(a1), y1o = cy + R * Math.sin(a1);
            const x1i = cx + r * Math.cos(a1), y1i = cy + r * Math.sin(a1);
            const x0i = cx + r * Math.cos(a0), y0i = cy + r * Math.sin(a0);
            const path =
                `M ${x0o} ${y0o} A ${R} ${R} 0 ${large} 1 ${x1o} ${y1o} ` +
                `L ${x1i} ${y1i} A ${r} ${r} 0 ${large} 0 ${x0i} ${y0i} Z`;
            segs.push({ ...p, path, pct: Math.round((100 * p.value) / total) });
        }
        const rated = total - (s.unrated || 0);
        const posPct = rated ? Math.round((100 * (s.positive || 0)) / rated) : null;
        return { segs, total, posPct };
    }

    // --------------------------------------------------------------- drilldown
    openConversations() {
        // Jump to the pivot report scoped roughly to this view.
        this.action.doAction("cx_module.action_cx_report_agent");
    }
}

registry.category("actions").add("cx_dashboard", CxDashboard);
