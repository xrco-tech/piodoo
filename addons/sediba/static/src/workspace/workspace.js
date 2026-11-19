/** @odoo-module **/

import { Component, markup, onWillStart, useState } from "@odoo/owl";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
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
// Why a company doc is in the review list.
const REVIEW_LABELS = {
    due: _t("Read again"),
    draft: _t("Draft doc"),
    changes: _t("Not published"),
    note: _t("Note"),
};
// What to ask before a button that takes something away.
const CONFIRM = {
    take_down: _t("The apps will stop showing this doc until it is published again. Take it down?"),
    archive: _t("This doc will leave Sediba and the apps. It can be brought back from Configuration. Archive it?"),
    restore: _t("The working text will be replaced by this version. Nothing changes in the apps until you publish. Bring it back?"),
};

/**
 * The Sediba workspace: company docs and research topics down the side, and
 * one page at a time beside them (overview, a doc to read or write, a topic
 * with its findings, one finding, the lists, the runs). It reads through
 * sediba.workspace. Research records are changed in their own form; a
 * company doc is written on the page itself.
 */
export class SedibaWorkspace extends Component {
    static template = "sediba.Workspace";
    static components = { Wysiwyg };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        // Opened from inside another app: only what is shown in that app.
        this.space = (this.props.action.params || {}).space || false;
        this.pills = PILLS;
        this.statusLabels = STATUS_LABELS;
        this.emptyColumn = EMPTY_COLUMN;
        this.reviewLabels = REVIEW_LABELS;
        this.editor = null;
        this.editorConfig = {};
        this.state = useState({
            view: "overview", // overview | doc | docedit | docs | topic | finding | list | runs
            nav: {
                topics: [], docs: [], templates: [], all: 0, review: 0, runs: 0, doc_count: 0, doc_review: 0,
                space: false, reference: false, can_edit: false, can_write: false,
            },
            data: null,
            topicId: false,
            findingId: false,
            docId: false,
            versionId: false, // an older version of the open doc
            draft: null, // the doc being written
            editorKey: 0,
            dirty: false,
            saving: false,
            newDocFrom: { template: "blank", parentId: false },
            docHits: [], // docs that match the sidebar search
            open: { docs: true, research: true },
            newMenu: false,
            history: false,
            telling: false,
            noteText: "",
            find: "", // "find a question" on an FAQ page
            pill: "all",
            search: "", // the sidebar search, across docs and findings
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
            } else if (params.doc_id) {
                this.state.view = "doc";
                this.state.docId = params.doc_id;
            }
            await this.load();
        });
    }

    get searchLabel() {
        return this.state.nav.reference ? _t("Search Reference") : _t("Search docs and findings");
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    async load() {
        const s = this.state;
        s.loading = true;
        const calls = {
            overview: ["ws_overview", [this.space]],
            doc: ["ws_doc", [s.docId, this.space, s.versionId]],
            docedit: ["ws_doc_edit", [s.docId, s.newDocFrom.parentId, s.newDocFrom.template]],
            docs: ["ws_docs", ["", this.space]],
            topic: ["ws_topic", [s.topicId, s.topicSearch, this.space]],
            finding: ["ws_finding", [s.findingId, this.space]],
            list: ["ws_findings", [s.pill, s.search, 0, PAGE, this.space]],
            runs: ["ws_runs", [0, PAGE, this.space]],
        };
        const [method, args] = calls[s.view];
        const [nav, data, hits] = await Promise.all([
            this.orm.call(WS, "ws_nav", [this.space]),
            this.orm.call(WS, method, args),
            s.view === "list" && s.search ? this.orm.call(WS, "ws_docs", [s.search, this.space]) : { rows: [] },
        ]);
        s.nav = nav;
        s.docHits = hits.rows;
        if (data === false) {
            // The record is gone: fall back to the overview.
            this.notification.add(_t("That record no longer exists."), { type: "warning" });
            s.view = "overview";
            s.data = await this.orm.call(WS, "ws_overview", [this.space]);
        } else if (s.view === "docedit") {
            this.startEditing(data);
        } else {
            s.data = this.prepared(data);
        }
        s.loading = false;
    }

    /** A doc's text is HTML the server has already cleaned. */
    prepared(data) {
        if (this.state.view === "doc" && data.body) {
            data.body = markup(data.body);
        }
        return data;
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

    async go(view, extra = {}) {
        if (this.state.view === "docedit" && this.state.dirty && !(await this.sure(
            _t("You have changes that are not saved. Leave without saving them?"), _t("Leave")))) {
            return;
        }
        Object.assign(
            this.state,
            { view, browsing: false, data: null, dirty: false, newMenu: false, history: false, telling: false,
              noteText: "", find: "", versionId: false },
            extra
        );
        return this.load();
    }

    openOverview() {
        return this.go("overview");
    }

    openDoc(id) {
        return this.go("doc", { docId: id });
    }

    openDocs() {
        return this.go("docs");
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

    isDoc(id) {
        return ["doc", "docedit"].includes(this.state.view) && this.state.docId === id;
    }

    evidenceText(evidence) {
        if (!evidence.parts.length) {
            return evidence.unopened ? _t("No source opened yet") : _t("No sources yet");
        }
        return evidence.parts.map((p) => `${p.count} × ${p.label}`).join(", ");
    }

    /** Ask before something that takes away. Resolves true on yes. */
    sure(body, confirmLabel) {
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                body,
                confirmLabel: confirmLabel || _t("Yes"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
                dismiss: () => resolve(false),
            });
        });
    }

    // ── Reading a company doc ────────────────────────────────────────────────

    get shownQuestions() {
        const find = this.state.find.trim().toLowerCase();
        const questions = this.state.data.questions;
        return find
            ? questions.filter((q) => `${q.name} ${q.answer}`.toLowerCase().includes(find))
            : questions;
    }

    async copyAnswer(q) {
        try {
            await browser.navigator.clipboard.writeText(q.answer);
            this.notification.add(_t("Answer copied."), { type: "success" });
        } catch {
            this.notification.add(_t("Could not copy. Select the answer and copy it by hand."), { type: "warning" });
        }
    }

    viewVersion(id) {
        return this.go("doc", { docId: this.state.docId, versionId: id, history: true });
    }

    async sendNote() {
        const text = this.state.noteText.trim();
        if (!text) {
            return;
        }
        await this.orm.call(WS, "ws_doc_note", [this.state.docId, text, this.space]);
        this.state.telling = false;
        this.state.noteText = "";
        this.notification.add(_t("Sent to the owner. Thank you."), { type: "success" });
        if (!this.space) {
            await this.load();
        }
    }

    async noteDone(id) {
        this.state.data = this.prepared(await this.orm.call(WS, "ws_doc_note_done", [id]));
        this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
    }

    /** The buttons beside a doc: publish, take_down, read_again, restore, archive. */
    async docDo(what, versionId = false) {
        if (CONFIRM[what] && !(await this.sure(CONFIRM[what]))) {
            return;
        }
        const result = await this.orm.call(WS, "ws_doc_do", [this.state.docId, what, versionId]);
        if (what === "archive") {
            return this.go("overview");
        }
        this.state.versionId = false;
        this.state.data = this.prepared(result);
        this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
        if (what === "publish") {
            this.notification.add(_t("Published."), { type: "success" });
        }
    }

    // ── Writing a company doc ────────────────────────────────────────────────

    newDoc(template, parentId = false) {
        return this.go("docedit", { docId: false, newDocFrom: { template, parentId } });
    }

    editDoc() {
        return this.go("docedit", { docId: this.state.docId, newDocFrom: { template: "blank", parentId: false } });
    }

    startEditing(data) {
        data.parent_id = data.parent_id || 0;
        this.editor = null;
        this.editorConfig = {
            content: data.body || "<p><br></p>",
            Plugins: MAIN_PLUGINS,
            onChange: () => this.touch(),
            getRecordInfo: () => ({ resModel: "sediba.doc", resId: data.id || false }),
        };
        this.state.draft = data;
        this.state.data = data;
        this.state.dirty = false;
        this.state.editorKey++;
    }

    onEditorLoad(editor) {
        this.editor = editor;
    }

    touch() {
        this.state.dirty = true;
    }

    addQuestion() {
        this.state.draft.questions.push({ name: "", answer: "" });
        this.touch();
    }

    removeQuestion(index) {
        this.state.draft.questions.splice(index, 1);
        this.touch();
    }

    moveQuestion(index, by) {
        const questions = this.state.draft.questions;
        const [moved] = questions.splice(index, 1);
        questions.splice(index + by, 0, moved);
        this.touch();
    }

    toggleSpace(id) {
        const ids = this.state.draft.space_ids;
        const at = ids.indexOf(id);
        if (at === -1) {
            ids.push(id);
        } else {
            ids.splice(at, 1);
        }
        this.touch();
    }

    async saveDoc(publish) {
        const e = this.state.draft;
        if (!e.name.trim()) {
            this.notification.add(_t("Give the doc a title first."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            const id = await this.orm.call(WS, "ws_doc_save", [
                e.id,
                {
                    name: e.name,
                    summary: e.summary,
                    body: this.editor ? this.editor.getContent() : e.body,
                    questions: e.questions.map((q) => ({ name: q.name, answer: q.answer })),
                    owner_id: e.owner_id || false,
                    parent_id: e.parent_id || false,
                    space_ids: [...e.space_ids],
                    ai_allowed: e.ai_allowed,
                    read_again: e.read_again,
                },
                publish,
            ]);
            this.state.dirty = false;
            this.notification.add(publish ? _t("Published.") : _t("Saved."), { type: "success" });
            await this.go("doc", { docId: id });
        } finally {
            this.state.saving = false;
        }
    }

    cancelEdit() {
        return this.state.docId ? this.go("doc", { docId: this.state.docId }) : this.go("overview");
    }

    // ── Changing research ────────────────────────────────────────────────────

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
