/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";

const WS = "contact.centre.workspace";
const TEMPLATE = "contact.centre.template";
const PAGE = 40;
const ICON = { whatsapp: "fa-whatsapp", sms: "fa-commenting-o", email: "fa-envelope-o" };
// Characters an SMS carries in its plain alphabet; anything else makes every
// SMS shorter (70 characters instead of 160).
const GSM = /^[A-Za-z0-9 \r\n@£$¥èéùìòÇØøÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ!"#¤%&'()*+,\-./:;<=>?¡ÄÖÑÜ§¿äöñüà^{}\\[~\]|€]*$/;

/** The Templates section: every channel's message templates, and one beside the list. */
export class ContactCentreTemplates extends Component {
    static template = "contact_centre_workspace.Templates";
    static props = {
        boot: Object,
        setPane: Function,
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
            tpl: null,
            loadingTpl: false,
            infoOpen: true,
            form: null,            // { name, channel, body, notes, error, saving } while writing or editing
            adding: false,
            working: false,
        });
        this.searchLater = useDebounced(() => this.loadList(), 300);
        onWillStart(() => this.loadList());
    }

    // ── Loading ──────────────────────────────────────────────────────────
    async loadList(limit = PAGE) {
        this.state.loading = true;
        try {
            const result = await this.orm.call(WS, "ws_templates", [], {
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
        const result = await this.orm.call(WS, "ws_templates", [], {
            pill: this.state.pill, search: this.state.search, offset: this.state.rows.length, limit: PAGE,
        });
        this.state.rows = this.state.rows.concat(result.rows);
        this.state.more = result.more;
    }

    async open(id) {
        this.state.sel = id;
        this.state.form = null;
        this.state.adding = false;
        this.props.setPane("thread");
        this.state.loadingTpl = !this.state.tpl;
        try {
            const tpl = await this.orm.call(WS, "ws_template", [id]);
            if (this.state.sel === id) {
                this.state.tpl = tpl;
            }
        } finally {
            this.state.loadingTpl = false;
        }
    }

    // ── List ─────────────────────────────────────────────────────────────
    get pills() {
        return [
            { key: "all", label: _t("All") },
            { key: "whatsapp", label: "WhatsApp" },
            { key: "sms", label: "SMS" },
            { key: "email", label: _t("Email") },
            { key: "archived", label: _t("Archived") },
        ];
    }

    get totalText() {
        const total = this.state.total;
        return total === 1 ? _t("1 template") : _t("%s templates", total);
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
        return ICON[channel] || "fa-file-text-o";
    }

    // ── One template ─────────────────────────────────────────────────────
    full(value) {
        return value ? deserializeDateTime(value).toFormat("d MMM yyyy, HH:mm") : "";
    }

    /** "142 characters", and for an SMS how many it will be sent as. */
    size(channel, body) {
        const length = (body || "").length;
        const characters = length === 1 ? _t("1 character") : _t("%s characters", length);
        if (channel !== "sms" || !length) {
            return characters;
        }
        const plain = GSM.test(body);
        const [one, part] = plain ? [160, 153] : [70, 67];
        const count = length <= one ? 1 : Math.ceil(length / part);
        const sms = count === 1 ? _t("1 SMS") : _t("%s SMSes each time it is sent", count);
        return plain ? `${characters} · ${sms}` : `${characters} · ${sms} (${_t("it has characters outside the plain SMS alphabet")})`;
    }

    get facts() {
        const tpl = this.state.tpl;
        return [
            { label: _t("Channel"), value: tpl.channel_label },
            { label: _t("Times sent"), value: String(tpl.sent) },
            { label: _t("Last sent"), value: this.full(tpl.last_sent) },
        ].filter((d) => d.value);
    }

    /** The template's form, for the link to an approved WhatsApp template and its history. */
    openRecord() {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: TEMPLATE, res_id: this.state.tpl.id, views: [[false, "form"]],
        });
    }

    // ── Writing, correcting, archiving ───────────────────────────────────
    edit() {
        const tpl = this.state.tpl;
        this.state.adding = false;
        this.state.form = { name: tpl.name, channel: tpl.channel, body: tpl.body, notes: tpl.notes, error: "", saving: false };
    }

    add() {
        const channel = ["whatsapp", "sms", "email"].includes(this.state.pill) ? this.state.pill : "whatsapp";
        this.state.adding = true;
        this.state.form = { name: "", channel, body: "", notes: "", error: "", saving: false };
        this.props.setPane("thread");
    }

    cancel() {
        this.state.form = null;
        if (this.state.adding) {
            this.state.adding = false;
            if (!this.state.tpl) {
                this.props.setPane("list");
            }
        }
    }

    onField(ev) {
        this.state.form[ev.target.name] = ev.target.value;
    }

    async save() {
        const form = this.state.form;
        if (!form || form.saving) {
            return;
        }
        const vals = { name: form.name, channel: form.channel, body_text: form.body, notes: form.notes };
        const id = this.state.adding ? false : this.state.sel;
        form.saving = true;
        form.error = "";
        try {
            const tpl = await this.orm.silent.call(WS, "ws_template_save", [id, vals]);
            this.state.tpl = tpl;
            this.state.sel = tpl.id;
            this.state.form = null;
            this.state.adding = false;
            await this.loadList(Math.max(PAGE, this.state.rows.length));
        } catch (error) {
            // What is missing or not allowed goes under the fields.
            form.saving = false;
            form.error = (error && error.data && error.data.message) || _t("That could not be saved.");
        }
    }

    async archive(archive) {
        if (this.state.working) {
            return;
        }
        this.state.working = true;
        try {
            this.state.tpl = await this.orm.call(WS, "ws_template_archive", [this.state.sel, archive]);
            await this.loadList(Math.max(PAGE, this.state.rows.length));
        } finally {
            this.state.working = false;
        }
    }

    // ── Panes ────────────────────────────────────────────────────────────
    showList() {
        this.props.setPane("list");
    }

    showTemplate() {
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
