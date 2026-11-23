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
import { SedibaFlowBlock, SedibaFlowEditor } from "./flow";
import { SedibaVisual, SedibaVisualBlock } from "./visual";

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
// What the left panel remembers between visits, on this device only.
const KEEP = "sediba.panel.";

function remembered(name, fallback) {
    try {
        const kept = browser.localStorage.getItem(KEEP + name);
        return kept === null ? fallback : JSON.parse(kept);
    } catch {
        return fallback;
    }
}

function remember(name, value) {
    try {
        browser.localStorage.setItem(KEEP + name, JSON.stringify(value));
    } catch {
        // Private windows and blocked storage: the panel still works, it just forgets.
    }
}

export class SedibaWorkspace extends Component {
    static template = "sediba.Workspace";
    static components = { Wysiwyg, SedibaFlowBlock, SedibaFlowEditor, SedibaVisual, SedibaVisualBlock };
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
            flowKey: false, // the diagram open in the editor, while a doc is being written
            dirty: false,
            saving: false,
            newDocFrom: { template: "blank", parentId: false },
            docHits: [], // docs that match the sidebar search
            open: { docs: true, research: true, collections: true, ...remembered("open", {}) },
            side: remembered("side", true), // the left panel is open
            props: remembered("props", true), // the Properties panel on the right is open
            shut: remembered("shut", {}), // docs whose pages are folded away, by id
            newMenu: false,
            history: false,
            telling: false,
            noteText: "",
            find: "", // "find a question" on an FAQ page
            pill: "all",
            search: "", // the sidebar search, across docs and findings
            topicSearch: "", // the search inside one topic
            board: true, // a topic's findings as a board, or as a list
            visual: true, // a topic's "What we know" as blocks, or as text
            visualKeys: [], // the visual blocks in the doc being written: "<block>_<topic id>"
            visualPick: { topic: "", block: "all" },
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
        for (const part of data.parts || []) {
            if (part.html) {
                part.html = markup(part.html);
            }
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
            { view, browsing: false, data: null, dirty: false, flowKey: false, newMenu: false, history: false, telling: false,
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

    // ── The left panel ───────────────────────────────────────────────────────

    get sideLabel() {
        return this.state.side ? _t("Close the panel") : _t("Open the panel");
    }

    toggleSide() {
        this.state.side = !this.state.side;
        remember("side", this.state.side);
    }

    get propsLabel() {
        return this.state.props ? _t("Close Properties") : _t("Open Properties");
    }

    toggleProps() {
        this.state.props = !this.state.props;
        remember("props", this.state.props);
    }

    toggleGroup(name) {
        this.state.open[name] = !this.state.open[name];
        remember("open", this.state.open);
    }

    /** A doc's pages show unless they were folded away. The open page is never hidden. */
    pagesOpen(doc) {
        return !this.state.shut[doc.id] || doc.pages.some((page) => this.isDoc(page.id));
    }

    twistLabel(doc) {
        return this.pagesOpen(doc) ? _t("Hide the pages under %s", doc.name) : _t("Show the pages under %s", doc.name);
    }

    toggleDoc(id) {
        const doc = this.state.nav.docs.find((d) => d.id === id);
        if (this.pagesOpen(doc)) {
            this.state.shut[id] = true;
            // Folding the doc that holds the open page: step up to the doc itself.
            if (doc.pages.some((page) => this.isDoc(page.id))) {
                this.openDoc(id);
            }
        } else {
            delete this.state.shut[id];
        }
        remember("shut", this.state.shut);
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
            content: this.lockFlowBlocks(data.body) || "<p><br></p>",
            Plugins: MAIN_PLUGINS,
            onChange: () => this.touch(),
            getRecordInfo: () => ({ resModel: "sediba.doc", resId: data.id || false }),
        };
        data.flows = data.flows || {};
        this.state.visualKeys = [...new Set(
            [...(data.body || "").matchAll(/o_sdb_vis_((?:all|tiles|bars|dates|orgs)_\d+)/g)].map((found) => found[1])
        )];
        const topics = (data.choices || {}).visual_topics || [];
        this.state.visualPick = { topic: topics.length ? String(topics[0][0]) : "", block: "all" };
        this.state.draft = data;
        this.state.data = data;
        this.state.dirty = false;
        this.state.editorKey++;
        // Came here from "Edit diagram" on the doc: open that diagram.
        this.state.flowKey = this.openFlowNext && data.flows[this.openFlowNext] ? this.openFlowNext : false;
        this.openFlowNext = false;
    }

    onEditorLoad(editor) {
        // Called before the editor has a place on the page: only keep hold of it.
        this.editor = editor;
    }

    /** A click in the text: on a diagram's block, it opens that diagram. */
    onTextClick(ev) {
        const block = ev.target.closest && ev.target.closest(".o_sdb_editable .o_sdb_flow");
        const key = block && this.flowKeyOf(block);
        if (key && this.state.draft.flows[key]) {
            this.state.flowKey = key;
        }
    }

    /** The doc's text with its diagram blocks made read-only, for the editor. */
    lockFlowBlocks(body) {
        if (!body || !(body.includes("o_sdb_flow") || body.includes("o_sdb_vis"))) {
            return body;
        }
        const holder = new DOMParser().parseFromString(`<div>${body}</div>`, "text/html").body.firstChild;
        for (const block of holder.querySelectorAll(".o_sdb_flow, .o_sdb_vis")) {
            block.setAttribute("contenteditable", "false");
        }
        return holder.innerHTML;
    }

    // ── Flow diagrams in a doc ───────────────────────────────────────────────

    flowKeyOf(block) {
        const found = /(?:^|\s)o_sdb_flow_([a-z0-9]+)(?:\s|$)/.exec(block.className || "");
        return found ? found[1] : false;
    }

    flowLabel(flow) {
        return _t("Flow diagram: %(name)s (%(count)s steps)", { name: flow.name, count: flow.steps.length });
    }

    /** The diagrams of the doc being written, in the order they were added. */
    get draftFlows() {
        return Object.entries(this.state.draft.flows || {}).map(([key, flow]) => ({ key, flow }));
    }

    flowBlock(key) {
        const editable = this.editor && this.editor.editable;
        return editable ? editable.querySelector(`.o_sdb_flow_${key}`) : null;
    }

    /** Tell the text editor its content changed by our hand, so undo and save see it. */
    editorChanged() {
        const shared = (this.editor && this.editor.shared) || {};
        try {
            if (shared.history && shared.history.addStep) {
                shared.history.addStep();
            } else if (shared.addStep) {
                shared.addStep();
            } else if (this.editor && this.editor.dispatch) {
                this.editor.dispatch("ADD_STEP");
            }
        } catch {
            // The text is still read from the page when the doc is saved.
        }
        this.touch();
    }

    // ── Visual blocks in a doc ───────────────────────────────────────────────

    /** "bars_14" as words: which block of which topic. */
    visualLabel(key) {
        const [block, topicId] = key.split("_");
        const choices = this.state.draft.choices;
        const topic = choices.visual_topics.find((t) => String(t[0]) === topicId);
        const kind = choices.visual_blocks.find((b) => b[0] === block);
        return _t("Visual block: %(block)s, %(topic)s", {
            block: kind ? kind[1] : block,
            topic: topic ? topic[1] : _t("a topic that is gone"),
        });
    }

    /** Part of a topic's visual summary, on a line of its own after the cursor's line. */
    insertVisual() {
        const pick = this.state.visualPick;
        if (!this.editor || !this.editor.editable || !pick.topic) {
            return;
        }
        const key = `${pick.block}_${pick.topic}`;
        if (this.state.visualKeys.includes(key)) {
            this.notification.add(_t("That block is already in this doc."), { type: "warning" });
            return;
        }
        const block = this.editor.editable.ownerDocument.createElement("div");
        block.className = `o_sdb_vis o_sdb_vis_${key}`;
        block.setAttribute("contenteditable", "false");
        block.textContent = this.visualLabel(key);
        this.placeBlock(block);
        this.state.visualKeys.push(key);
        this.editorChanged();
    }

    removeVisual(key) {
        const editable = this.editor && this.editor.editable;
        for (const block of editable ? editable.querySelectorAll(`.o_sdb_vis_${key}`) : []) {
            block.remove();
        }
        this.state.visualKeys = this.state.visualKeys.filter((other) => other !== key);
        this.editorChanged();
    }

    /** Put a block on a line of its own after the line the cursor is in, with a line to type on after it. */
    placeBlock(block) {
        const editable = this.editor.editable;
        const doc = editable.ownerDocument;
        const selection = doc.getSelection();
        let line = selection && selection.rangeCount && editable.contains(selection.anchorNode) ? selection.anchorNode : null;
        while (line && line.parentNode !== editable) {
            line = line.parentNode;
        }
        if (line) {
            line.after(block);
        } else {
            editable.append(block);
        }
        if (!block.nextElementSibling) {
            const after = doc.createElement("p");
            after.append(doc.createElement("br"));
            block.after(after);
        }
    }

    /** A new diagram, on a line of its own after the line the cursor is in. */
    insertFlow() {
        if (!this.editor || !this.editor.editable) {
            return;
        }
        const flows = this.state.draft.flows;
        let count = 1;
        while (flows[`f${count}`]) {
            count++;
        }
        const key = `f${count}`;
        flows[key] = { name: _t("Flow diagram"), steps: [] };
        const editable = this.editor.editable;
        const doc = editable.ownerDocument;
        const block = doc.createElement("div");
        block.className = `o_sdb_flow o_sdb_flow_${key}`;
        block.setAttribute("contenteditable", "false");
        block.textContent = this.flowLabel(flows[key]);
        this.placeBlock(block);
        this.editorChanged();
        this.state.flowKey = key;
    }

    openFlow(key) {
        this.state.flowKey = key;
    }

    onFlowDone(flow) {
        const key = this.state.flowKey;
        const before = JSON.stringify(this.state.draft.flows[key]);
        this.state.draft.flows[key] = flow;
        this.state.flowKey = false;
        const block = this.flowBlock(key);
        if (block) {
            block.textContent = this.flowLabel(flow);
        }
        if (JSON.stringify(flow) !== before) {
            this.editorChanged();
        }
    }

    removeFlow(key) {
        const block = this.flowBlock(key);
        if (block) {
            block.remove();
        }
        delete this.state.draft.flows[key];
        this.editorChanged();
    }

    /** From the doc as it is read: go and edit one of its diagrams. */
    editFlow(key) {
        this.openFlowNext = key;
        return this.editDoc();
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
                    flows: JSON.parse(JSON.stringify(e.flows || {})),
                    questions: e.questions.map((q) => ({ name: q.name, answer: q.answer })),
                    owner_id: e.owner_id || false,
                    parent_id: e.parent_id || false,
                    space_ids: [...e.space_ids],
                    ai_allowed: e.ai_allowed,
                    public_allowed: e.public_allowed,
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

    async toggleTopicAi(ev) {
        // Keep what was typed in the topic's search box: only the switch changed.
        const d = await this.orm.call(WS, "ws_set_topic_ai", [this.state.topicId, ev.target.checked, this.space]);
        if (d) {
            this.state.data.ai_allowed = d.ai_allowed;
        }
    }

    async toggleTopicPublic(ev) {
        const d = await this.orm.call(WS, "ws_set_topic_ai", [this.state.topicId, ev.target.checked, this.space, true]);
        if (d) {
            this.state.data.public_allowed = d.public_allowed;
        }
    }

    async toggleTopicSpace(id) {
        const ids = this.state.data.space_ids.filter((spaceId) => spaceId !== id);
        if (ids.length === this.state.data.space_ids.length) {
            ids.push(id);
        }
        const d = await this.orm.call(WS, "ws_set_topic_spaces", [this.state.topicId, ids, this.space]);
        if (d) {
            this.state.data.space_ids = d.space_ids;
        }
    }

    /** The apps a topic is shown in, by name: for someone who may not change them. */
    get topicSpaces() {
        const d = this.state.data;
        return d.spaces.filter((space) => d.space_ids.includes(space[0])).map((space) => space[1]);
    }

    // ── A doc's properties, changed on the reading page ──────────────────────

    async setDocProp(vals) {
        const d = await this.orm.call(WS, "ws_doc_set", [this.state.docId, vals]);
        if (d) {
            this.state.data = this.prepared(d);
            this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
        }
    }

    toggleDocSpace(id) {
        const now = this.state.data.props.space_ids;
        const ids = now.filter((spaceId) => spaceId !== id);
        return this.setDocProp({ space_ids: ids.length === now.length ? [...ids, id] : ids });
    }

    async toggleReview() {
        const f = this.state.data;
        this.state.data = await this.orm.call(WS, "ws_set_review", [f.id, !f.review, this.space]);
        this.state.nav = await this.orm.call(WS, "ws_nav", [this.space]);
    }
}

registry.category("actions").add("sediba_workspace", SedibaWorkspace);
