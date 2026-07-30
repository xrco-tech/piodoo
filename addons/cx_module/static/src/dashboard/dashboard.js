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
            days: 30,
            team: "",
            loading: true,
            data: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("cx.dashboard", "get_metrics", [], {
                scope: this.state.scope,
                days: this.state.days,
                team: this.state.team || null,
            });
        } finally {
            this.state.loading = false;
        }
    }

    get dayOptions() {
        return DAY_OPTIONS;
    }

    setDays(d) {
        this.state.days = d;
        this.load();
    }

    onTeamChange(ev) {
        this.state.team = ev.target.value;
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
