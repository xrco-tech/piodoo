/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { when, dialWhatsApp, dialVoip } from "./util";

const WS = "contact.centre.workspace";
const PAGE = 40;
const BADGE = { whatsapp: "WA", sms: "SMS", voice: "Tel", email: "@" };

/** The Contacts section: the directory, and one contact beside it. */
export class ContactCentreContacts extends Component {
    static template = "contact_centre_workspace.Contacts";
    static props = {
        boot: Object,
        openId: { type: [Number, Boolean], optional: true },
        setPane: Function,
        openConversation: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            pill: "all",
            search: "",
            tagId: false,
            tags: [],
            rows: [],
            total: 0,
            more: false,
            loading: true,
            sel: false,
            contact: null,
            loadingContact: false,
            infoOpen: true,
            form: null,            // { name, phone, email, error, saving } while editing or adding
            adding: false,
        });
        this.when = when;
        this.searchLater = useDebounced(() => this.loadList(), 300);
        onWillStart(async () => {
            const [tags] = await Promise.all([this.orm.call(WS, "ws_contact_tags", []), this.loadList()]);
            this.state.tags = tags;
            if (this.props.openId) {
                await this.open(this.props.openId);
            }
        });
    }

    // ── Loading ──────────────────────────────────────────────────────────
    get filters() {
        return { pill: this.state.pill, search: this.state.search, tag_id: this.state.tagId };
    }

    async loadList(limit = PAGE) {
        this.state.loading = true;
        try {
            const result = await this.orm.call(WS, "ws_contacts", [], { ...this.filters, offset: 0, limit });
            this.state.rows = result.rows;
            this.state.total = result.total;
            this.state.more = result.more;
        } finally {
            this.state.loading = false;
        }
    }

    async loadMore() {
        const result = await this.orm.call(WS, "ws_contacts", [], {
            ...this.filters, offset: this.state.rows.length, limit: PAGE,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async open(id) {
        this.state.sel = id;
        this.state.form = null;
        this.state.adding = false;
        this.props.setPane("thread");
        this.state.loadingContact = !this.state.contact;
        try {
            const contact = await this.orm.call(WS, "ws_contact", [id]);
            if (this.state.sel === id) {
                this.state.contact = contact;
            }
        } finally {
            this.state.loadingContact = false;
        }
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        return [
            { key: "all", label: _t("All") },
            { key: "recent", label: _t("Last 30 days") },
            { key: "never", label: _t("Never contacted") },
            { key: "campaign", label: _t("In a running campaign") },
        ];
    }

    get totalText() {
        const total = this.state.total;
        return total === 1 ? _t("1 contact") : _t("%s contacts", total);
    }

    setPill(key) {
        this.state.pill = key;
        this.loadList();
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.searchLater();
    }

    onTag(ev) {
        this.state.tagId = parseInt(ev.target.value, 10) || false;
        this.loadList();
    }

    /** Second line of a row: the number, else the email. */
    line(row) {
        return row.phone || row.email || _t("No phone number or email");
    }

    // ── One contact ──────────────────────────────────────────────────────
    badge(channel) {
        return BADGE[channel] || "";
    }

    full(value) {
        return value ? deserializeDateTime(value).toFormat("d MMM yyyy, HH:mm") : "";
    }

    stateLabel(state) {
        return { open: _t("Open"), pending: _t("Pending"), resolved: _t("Resolved") }[state] || state;
    }

    stateClass(state) {
        return { open: "plain", pending: "warn", resolved: "ok" }[state] || "plain";
    }

    get details() {
        const contact = this.state.contact;
        return [
            { label: _t("Channels"), value: contact.channels.join(", ") },
            { label: _t("First contact"), value: this.full(contact.first) },
            { label: _t("Last contact"), value: this.full(contact.last) },
        ].filter((d) => d.value);
    }

    openConversation() {
        this.props.openConversation(this.state.contact.id);
    }

    callWhatsApp() {
        const contact = this.state.contact;
        dialWhatsApp(this.env.services, { phone: contact.phone, name: contact.name, partnerId: contact.partner_id });
    }

    callVoip() {
        dialVoip(this.env.services, this.state.contact.phone);
    }

    /** The old form, for anything this card does not cover. */
    openRecord() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "contact.centre.contact",
            res_id: this.state.contact.id,
            views: [[false, "form"]],
        });
    }

    // ── Editing and adding ───────────────────────────────────────────────
    edit() {
        const contact = this.state.contact;
        this.state.adding = false;
        this.state.form = { name: contact.name, phone: contact.phone, email: contact.email, error: "", saving: false };
    }

    add() {
        this.state.adding = true;
        this.state.form = { name: "", phone: "", email: "", error: "", saving: false };
        this.props.setPane("thread");
    }

    cancel() {
        this.state.form = null;
        if (this.state.adding) {
            this.state.adding = false;
            if (!this.state.contact) {
                this.props.setPane("list");
            }
        }
    }

    onField(ev) {
        this.state.form[ev.target.name] = ev.target.value;
    }

    onFormKey(ev) {
        if (ev.key === "Enter") {
            this.save();
        } else if (ev.key === "Escape") {
            this.cancel();
        }
    }

    async save() {
        const form = this.state.form;
        if (!form || form.saving) {
            return;
        }
        const vals = { name: form.name, phone_number: form.phone, email: form.email };
        form.saving = true;
        form.error = "";
        try {
            if (this.state.adding) {
                const result = await this.orm.silent.call(WS, "ws_contact_create", [vals]);
                if (result.existing) {
                    this.notification.add(_t("That number already belongs to a contact. Here it is."), { type: "info" });
                }
                await Promise.all([this.loadList(Math.max(PAGE, this.state.rows.length)), this.open(result.id)]);
            } else {
                this.state.contact = await this.orm.silent.call(WS, "ws_contact_save", [this.state.sel, vals]);
                this.state.form = null;
                await this.loadList(Math.max(PAGE, this.state.rows.length));
            }
        } catch (error) {
            // What the server said (a missing name, a number that looks wrong) goes under the fields.
            form.saving = false;
            form.error = (error && error.data && error.data.message) || _t("That could not be saved.");
        }
    }

    hasTag(tag) {
        return this.state.contact.tag_ids.includes(tag.id);
    }

    async toggleTag(tag) {
        const contact = this.state.contact;
        const ids = this.hasTag(tag) ? contact.tag_ids.filter((id) => id !== tag.id) : contact.tag_ids.concat(tag.id);
        contact.tag_ids = await this.orm.call(WS, "ws_contact_set_tags", [contact.id, ids]);
        const row = this.state.rows.find((r) => r.id === contact.id);
        if (row) {
            row.tags = this.state.tags.filter((t) => contact.tag_ids.includes(t.id)).map((t) => t.name);
        }
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    showContact() {
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
