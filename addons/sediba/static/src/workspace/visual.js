/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Visual blocks: headline numbers, comparison bars, dates to know and
 * organisation cards, with tags and logos inside them.
 *
 * The server decides what is drawn (sediba.topic._visual): only facts on
 * verified findings, already sorted and scaled. This file only draws. Every
 * item names the finding it came from; with `onOpen` it is a button that
 * opens that finding.
 */
export class SedibaVisual extends Component {
    static template = "sediba.Visual";
    static props = {
        data: Object, // {tiles, charts, dates, orgs}
        onOpen: { type: Function, optional: true },
        orgsTitle: { type: Boolean, optional: true }, // head the cards "By organisation"
    };

    get tag() {
        return this.props.onOpen ? "button" : "div";
    }

    get buttonType() {
        return this.props.onOpen ? "button" : undefined;
    }

    open(findingId) {
        if (this.props.onOpen) {
            this.props.onOpen(findingId);
        }
    }

    logoUrl(org) {
        return `/web/image/sediba.organisation/${org.id}/logo`;
    }

    /** Which of the two series colours a bar wears: by the measure, never by rank. */
    seriesClass(chart, bar) {
        return `s${Math.max(0, chart.series.indexOf(bar.series))}`;
    }

    /** What a bar says on hover and to a screen reader: its measure and value. */
    barTitle(row, bar) {
        return bar.series ? `${bar.series}: ${bar.value}` : `${row.subject}: ${bar.value}`;
    }

    /** A bar with a value never vanishes: it keeps a sliver at the baseline. */
    barStyle(bar) {
        return `width: max(2px, ${bar.percent}%)`;
    }
}

/** A visual block as it shows inside a company doc: what it is, the blocks, and the same as text. */
export class SedibaVisualBlock extends Component {
    static template = "sediba.VisualBlock";
    static components = { SedibaVisual };
    static props = {
        visual: Object, // {block, block_label, topic: [id, name], data, lines, can_open}
        onOpen: { type: Function, optional: true },
        onOpenTopic: { type: Function, optional: true },
    };

    /** How many things the block draws: tiles, chart rows, dates and cards. */
    get count() {
        const d = this.props.visual.data;
        return d.tiles.length + d.charts.reduce((sum, chart) => sum + chart.rows.length, 0) + d.dates.length + d.orgs.length;
    }
}
