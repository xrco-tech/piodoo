# -*- coding: utf-8 -*-
"""What the workspace screen reads and changes for company docs.

Same shape as the research half: one `ws_*` call per page, `space` set when
the screen is opened from inside an app as its Reference. From inside an app
only published docs marked for that app show, always as their last published
version, and nothing can be changed except leaving a note for the owner.
"""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date, html2plaintext

from .sediba_doc import READ_AGAIN
from .sediba_fact import BLOCKS
from .sediba_flow import clean_doc, clean_flow, doc_parts, doc_text, flow_lines
from .sediba_workspace import DATE_FORMAT

# Starting points for a new doc. Headings only: the words are the writer's.
TEMPLATES = {
    'blank': ("Blank page", ""),
    'about': ("About us", "<h2>Who we are</h2><p><br></p><h2>What we do</h2><p><br></p>"
                          "<h2>Who we do it for</h2><p><br></p><h2>How to reach us</h2><p><br></p>"),
    'how': ("How we work", "<h2>When this applies</h2><p><br></p><h2>Steps</h2><ol><li><br></li></ol>"
                           "<h2>When you cannot help</h2><p><br></p>"),
    'faq': ("Questions and answers", ""),
    'policy': ("Policy", "<h2>The rule</h2><p><br></p><h2>Why we have it</h2><p><br></p>"
                         "<h2>What to do</h2><ul><li><br></li></ul><h2>Who to ask</h2><p><br></p>"),
}


class SedibaWorkspaceDocs(models.AbstractModel):
    _inherit = 'sediba.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────────

    @api.model
    def _can_write(self, space=False):
        return not space and self.env.user.has_group('sediba.group_writer')

    @api.model
    def _need_writer(self, space=False):
        if space:
            raise AccessError(_("The Reference inside an app is read-only. Change docs in the Library."))
        if not self.env.user.has_group('sediba.group_writer'):
            raise AccessError(_("Only a Library writer can change company docs."))

    @api.model
    def _docs(self, space=False):
        """Every doc. From inside an app: only the published ones shown there."""
        if not space:
            return self.env['sediba.doc'].search([])
        return self.env['sediba.doc'].search([('state', '=', 'published'), ('space_ids.code', '=', space)])

    def _doc_due(self, doc):
        return bool(doc.read_again_by and doc.read_again_by <= fields.Date.context_today(self))

    def _doc_shown(self, doc, space=False):
        """The title, line and date to show: the working copy in the Library, the
        last published version anywhere else."""
        version = doc._published() if space else False
        if version:
            return {'name': version.name, 'summary': version.summary or '',
                    'updated': format_date(self.env, version.published_on, date_format=DATE_FORMAT)}
        return {'name': doc.name, 'summary': doc.summary or '',
                'updated': format_date(self.env, doc.write_date, date_format=DATE_FORMAT)}

    def _doc_row(self, doc, space=False):
        row = self._doc_shown(doc, space)
        row.update({
            'id': doc.id,
            'icon': doc.icon_url,
            'state': doc.state,
            'changes': False if space else doc.has_changes,
            'due': False if space else self._doc_due(doc),
            'parent': [doc.parent_id.id, doc.parent_id.name] if doc.parent_id else False,
        })
        return row

    def _doc_tree(self, space=False):
        """Docs with their pages under them. A page whose parent does not
        show here stands at the top level."""
        docs = self._docs(space)
        tree = []
        for doc in docs.filtered(lambda d: d.parent_id not in docs):
            row = self._doc_row(doc, space)
            row['pages'] = [self._doc_row(page, space) for page in docs.filtered(lambda d, doc=doc: d.parent_id == doc)]
            tree.append(row)
        return tree

    def _doc_review(self):
        """What a writer should look at: docs past their date, drafts, docs
        with changes waiting, and notes people left."""
        docs = self._docs()
        lines = []
        for doc in docs:
            if self._doc_due(doc):
                lines.append({'id': doc.id, 'name': doc.name, 'kind': 'due', 'text': _(
                    "Should have been read again by %s. Read it through and confirm it is still right.",
                    format_date(self.env, doc.read_again_by, date_format=DATE_FORMAT))})
            if doc.state == 'draft':
                lines.append({'id': doc.id, 'name': doc.name, 'kind': 'draft',
                              'text': _("Not published, so the apps do not show it.")})
            elif doc.has_changes:
                lines.append({'id': doc.id, 'name': doc.name, 'kind': 'changes',
                              'text': _("Changed since it was published. The apps still show the older version.")})
        for note in self.env['sediba.doc.note'].search([('done', '=', False), ('doc_id', 'in', docs.ids)]):
            lines.append({'id': note.doc_id.id, 'name': note.doc_id.name, 'kind': 'note',
                          'text': _("%(who)s says: %(note)s", who=note.author or _("Someone"), note=note.name)})
        return lines

    # ── Reads ────────────────────────────────────────────────────────────────

    @api.model
    def ws_nav(self, space=False):
        nav = super().ws_nav(space)
        docs = self._docs(space)
        nav.update({
            'docs': self._doc_tree(space),
            'doc_count': len(docs),
            'doc_review': 0 if space else len(self._doc_review()),
            'can_write': self._can_write(space),
            'templates': [[key, label] for key, (label, _body) in TEMPLATES.items()] if self._can_write(space) else [],
        })
        return nav

    @api.model
    def ws_overview(self, space=False):
        data = super().ws_overview(space)
        docs = self._docs(space)
        data['docs'] = {
            'published': len(docs.filtered(lambda d: d.state == 'published')),
            'draft': 0 if space else len(docs.filtered(lambda d: d.state == 'draft')),
            'due': 0 if space else len(docs.filtered(self._doc_due)),
        }
        data['doc_review'] = [] if space else self._doc_review()
        if space:
            data['doc_cards'] = [self._doc_row(doc, space) for doc in docs]
            versions = self.env['sediba.doc.version'].search(
                [('doc_id', 'in', docs.ids)], order='published_on desc, id desc', limit=40)
            changed, seen = [], set()
            for version in versions:
                # Only the version a doc shows now, and each doc once.
                if version.doc_id.id in seen or version != version.doc_id._published():
                    continue
                seen.add(version.doc_id.id)
                changed.append({
                    'id': version.doc_id.id, 'name': version.name, 'new': version.number == 1,
                    'date': format_date(self.env, version.published_on, date_format=DATE_FORMAT)})
            data['doc_changed'] = changed[:5]
        else:
            data['doc_rows'] = [dict(
                self._doc_row(doc),
                owner=doc.owner_id.name or '',
                spaces=", ".join(doc.space_ids.mapped('name')),
                pages=len(doc.child_ids),
                read_again_by=self._date(doc.read_again_by),
            ) for doc in docs.filtered(lambda d: not d.parent_id)]
        return data

    @api.model
    def _visual_label(self, block, topic_id):
        """The line of words a visual block keeps in a doc's text, or False
        when its topic is gone."""
        topic = self.env['sediba.topic'].browse(topic_id).exists()
        if not topic or not topic.active:
            return False
        return _("Visual block: %(block)s, %(topic)s", block=dict(BLOCKS)[block], topic=topic.name)

    @api.model
    def _doc_parts(self, body, flows, space=False):
        """A doc cut into text, diagrams and visual blocks, each visual block
        filled from its topic's verified findings as they stand today. In an
        app, a block with nothing to draw is left out."""
        parts = []
        for part in doc_parts(body, flows):
            if 'visual' not in part:
                parts.append(part)
                continue
            block, topic = part['visual']['block'], self.env['sediba.topic'].browse(part['visual']['topic_id']).exists()
            if not topic or not topic.active:
                continue
            drawn = topic._visual_part(topic._visual(), block)
            if not drawn and space:
                continue
            parts.append({'visual': {
                'block': block,
                'block_label': dict(BLOCKS)[block],
                'topic': [topic.id, topic.name],
                'data': drawn,
                'lines': topic._visual_lines(drawn),
                # A finding opens only where the reader may see the topic.
                'can_open': topic in self._topics(space),
            }})
        return parts

    @api.model
    def ws_doc(self, doc_id, space=False, version_id=False):
        """One doc to read. In the Library: the working copy, or an older version
        when `version_id` is given. In an app: the last published version."""
        doc = self.env['sediba.doc'].browse(doc_id).exists() & self._docs(space)
        if not doc:
            return False
        version = doc._published() if space else doc.version_ids.filtered(lambda v: v.id == version_id)
        if version:
            questions = [{'name': q.get('name', ''), 'answer': q.get('answer', '')} for q in version.questions or []]
            name, summary, body, flows = version.name, version.summary, version.body, version.flows
        else:
            questions = [{'name': q.name, 'answer': q.answer or ''} for q in doc.question_ids]
            name, summary, body, flows = doc.name, doc.summary, doc.body, doc.flows
        visible_topics = self._topics(space)
        docs = self._docs(space)
        data = {
            'id': doc.id,
            'icon': doc.icon_url,
            'name': name,
            'summary': summary or '',
            'body': Markup(body) if html2plaintext(body or '').strip() else '',
            # The text cut at its flow diagrams, in the order the page draws them.
            'parts': self._doc_parts(body, flows, space),
            'questions': questions,
            'parent': [doc.parent_id.id, self._doc_shown(doc.parent_id, space)['name'], doc.parent_id.icon_url]
                      if doc.parent_id and doc.parent_id in docs else False,
            'pages': [self._doc_row(page, space) for page in docs.filtered(lambda d: d.parent_id == doc)],
            'owner': doc.owner_id.name or '',
            'updated': self._date((version.published_on if version else doc.write_date)),
            'topics': [{'id': t.id, 'name': t.name, 'verified': t.verified_count}
                       for t in doc.topic_ids if t in visible_topics],
            'reference': bool(space),
        }
        if space:
            return data
        data.update({
            'state': doc.state,
            'changes': doc.has_changes,
            'due': self._doc_due(doc),
            'viewing': {'number': version.number, 'date': self._date(version.published_on),
                        'by': version.published_by or '', 'id': version.id} if version else False,
            'spaces': doc.space_ids.mapped('name'),
            'ai_allowed': doc.ai_allowed,
            'public_allowed': doc.public_allowed,
            # What a writer changes right on the reading page.
            'props': self._doc_props(doc) if self._can_write() else False,
            'updated_by': doc.write_uid.name or '',
            'read_again': dict(READ_AGAIN).get(doc.read_again, ''),
            'read_again_by': self._date(doc.read_again_by),
            'last_read_on': self._date(doc.last_read_on),
            'versions': [{'id': v.id, 'number': v.number, 'date': self._date(v.published_on),
                          'by': v.published_by or '', 'name': v.name}
                         for v in doc.version_ids.sorted('number', reverse=True)],
            'notes': [{'id': n.id, 'text': n.name, 'author': n.author or '', 'space': n.space or '',
                       'date': self._date(n.create_date)} for n in doc.note_ids.filtered(lambda n: not n.done)],
        })
        return data

    @api.model
    def ws_docs(self, search='', space=False):
        """Every doc as a flat list, or the ones that match a search."""
        rows = []
        for doc in self._docs(space):
            version = doc._published() if space else False
            if search:
                source = version or doc
                questions = version.questions or [] if version else [
                    {'name': q.name, 'answer': q.answer} for q in doc.question_ids]
                text = " ".join(filter(None, [
                    source.name, source.summary, doc_text(source.body, source.flows),
                    *[q.get('name') or '' for q in questions], *[q.get('answer') or '' for q in questions]]))
                if search.lower() not in text.lower():
                    continue
            rows.append(dict(
                self._doc_row(doc, space),
                owner=doc.owner_id.name or '',
                spaces="" if space else ", ".join(doc.space_ids.mapped('name')),
                read_again_by=False if space else self._date(doc.read_again_by),
            ))
        return {'total': len(rows), 'rows': rows}

    @api.model
    def _doc_owners(self, doc):
        writers = self.env.ref('sediba.group_writer').users.filtered(lambda u: u.active and not u.share)
        return [[u.id, u.name] for u in (writers | doc.owner_id | self.env.user).sorted('name')]

    @api.model
    def _doc_props(self, doc):
        """The properties a writer sets beside a doc, with their choices."""
        return {
            'owner_id': doc.owner_id.id or 0,
            'space_ids': doc.space_ids.ids,
            'read_again': doc.read_again,
            'icon_app': doc.icon_app if doc.icon_url else '',
            # The link anyone can open without signing in, while it is on.
            'share': '/library/shared/%s' % doc.share_token if doc.share_token else False,
            'choices': {
                'owners': self._doc_owners(doc),
                'spaces': [[s.id, s.name] for s in self.env['sediba.space'].search([])],
                'read_again': READ_AGAIN,
                # The apps whose icon the doc can carry: [key, name, picture].
                'icons': [[key, icon['name'], icon['url']]
                          for key, icon in sorted(doc._app_icons().items(), key=lambda item: item[1]['name'])],
            },
        }

    @api.model
    def ws_doc_set(self, doc_id, vals):
        """Change a doc's properties from the reading page. They are not part
        of what is published, so they take effect at once."""
        self._need_writer()
        doc = self.env['sediba.doc'].browse(doc_id).exists()
        if not doc:
            return False
        record = {}
        if 'owner_id' in vals:
            record['owner_id'] = vals['owner_id'] or False
        if 'space_ids' in vals:
            record['space_ids'] = [(6, 0, self.env['sediba.space'].browse(vals['space_ids'] or []).exists().ids)]
        for key in ('ai_allowed', 'public_allowed'):
            if key in vals:
                record[key] = bool(vals[key])
        if 'icon_app' in vals:
            if vals['icon_app'] and vals['icon_app'] not in doc._app_icons():
                raise UserError(_("Choose the page icon from the list."))
            record['icon_app'] = vals['icon_app'] or False
        if 'read_again' in vals:
            if vals['read_again'] not in dict(READ_AGAIN):
                raise UserError(_("Choose how often it is read again from the list."))
            record['read_again'] = vals['read_again']
        if record:
            doc.write(record)
        if 'shared' in vals:
            doc.action_share(bool(vals['shared']))
        return self.ws_doc(doc.id)

    @api.model
    def ws_doc_edit(self, doc_id=False, parent_id=False, template='blank'):
        """What the editing page needs: the working copy (or a fresh one from
        a template) and the choices for its properties."""
        self._need_writer()
        Doc = self.env['sediba.doc']
        doc = Doc.browse(doc_id).exists()
        if doc_id and not doc:
            return False
        parent = Doc.browse(parent_id).exists()
        label, body = TEMPLATES.get(template, TEMPLATES['blank'])
        return {
            'id': doc.id or False,
            'name': doc.name or '',
            'summary': doc.summary or '',
            'body': doc.body or body if doc else body,
            'flows': doc.flows or {},
            'questions': [{'name': q.name, 'answer': q.answer or ''} for q in doc.question_ids]
                         or ([{'name': '', 'answer': ''}] if not doc and template == 'faq' else []),
            'owner_id': (doc.owner_id.id if doc else self.env.user.id) or False,
            'parent_id': (doc.parent_id.id if doc else parent.id) or False,
            'space_ids': (doc.space_ids if doc else parent.space_ids).ids,
            'ai_allowed': doc.ai_allowed if doc else True,
            'public_allowed': doc.public_allowed if doc else False,
            'read_again': doc.read_again if doc else '3',
            'state': doc.state if doc else 'draft',
            'changes': doc.has_changes if doc else False,
            'versions': len(doc.version_ids),
            'has_pages': bool(doc.child_ids),
            'choices': {
                'owners': self._doc_owners(doc),
                'parents': [[d.id, d.name] for d in Doc.search([('parent_id', '=', False), ('id', '!=', doc.id or 0)])],
                'spaces': [[s.id, s.name] for s in self.env['sediba.space'].search([])],
                'read_again': READ_AGAIN,
                # Visual blocks: which part of which topic's summary to show.
                'visual_blocks': [list(item) for item in BLOCKS],
                'visual_topics': [[t.id, t.name] for t in self.env['sediba.topic'].search([])],
            },
        }

    # ── Writes ───────────────────────────────────────────────────────────────

    @api.model
    def ws_doc_save(self, doc_id, vals, publish=False):
        """Save the editing page: a new doc when `doc_id` is empty. With
        `publish`, what was saved becomes the version the apps show."""
        self._need_writer()
        Doc = self.env['sediba.doc']
        doc = Doc.browse(doc_id).exists()
        if doc_id and not doc:
            return False
        name = (vals.get('name') or '').strip()
        if not name:
            raise UserError(_("Give the doc a title first."))
        body, flows = clean_doc(vals.get('body') or '', vals.get('flows'), self._visual_label)
        record = {
            'name': name,
            'summary': (vals.get('summary') or '').strip() or False,
            'body': body or False,
            'flows': flows or False,
            'owner_id': vals.get('owner_id') or False,
            'parent_id': vals.get('parent_id') or False,
            'space_ids': [(6, 0, vals.get('space_ids') or [])],
            'ai_allowed': bool(vals.get('ai_allowed')),
            'public_allowed': bool(vals.get('public_allowed')),
            'read_again': vals.get('read_again') or '3',
        }
        questions = [{'name': (q.get('name') or '').strip(), 'answer': (q.get('answer') or '').strip()}
                     for q in vals.get('questions') or []]
        questions = [q for q in questions if q['name']]
        if doc:
            doc.write(record)
            current = [{'name': q.name, 'answer': q.answer or ''} for q in doc.question_ids]
            if current != questions:
                doc.question_ids.unlink()
                doc.write({'question_ids': [(0, 0, dict(q, sequence=i)) for i, q in enumerate(questions)]})
        else:
            record['question_ids'] = [(0, 0, dict(q, sequence=i)) for i, q in enumerate(questions)]
            doc = Doc.create(record)
        if publish:
            doc.action_publish()
        return doc.id

    @api.model
    def ws_flow_text(self, flow):
        """A diagram as numbered steps, for the editor's "As text" tab: the
        same words the assistants read and the page prints."""
        self._need_writer()
        return flow_lines(clean_flow(flow))

    @api.model
    def ws_doc_do(self, doc_id, what, version_id=False):
        """The buttons beside a doc: publish, take_down, read_again, restore,
        archive."""
        self._need_writer()
        doc = self.env['sediba.doc'].browse(doc_id).exists()
        if not doc:
            return False
        if what == 'publish':
            doc.action_publish()
        elif what == 'take_down':
            doc.action_take_down()
        elif what == 'read_again':
            doc.action_read_again()
        elif what == 'restore':
            doc.action_restore(self.env['sediba.doc.version'].browse(version_id).exists())
        elif what == 'archive':
            if doc.child_ids:
                raise UserError(_("Move or remove the pages under '%s' first.", doc.name))
            doc.active = False
            return True
        else:
            return False
        return self.ws_doc(doc.id)

    @api.model
    def ws_doc_note(self, doc_id, text, space=False):
        """'Tell the owner', open to every reader, also from inside an app."""
        doc = self.env['sediba.doc'].browse(doc_id).exists() & self._docs(space)
        text = (text or '').strip()
        if not doc or not text:
            return False
        area = self.env['sediba.space'].search([('code', '=', space)], limit=1) if space else False
        # Readers cannot write in the Library; this one note is the exception.
        self.env['sediba.doc.note'].sudo().create({
            'doc_id': doc.id, 'name': text[:2000], 'author': self.env.user.name,
            'space': area.name if area else 'Library'})
        return True

    @api.model
    def ws_doc_note_done(self, note_id):
        self._need_writer()
        note = self.env['sediba.doc.note'].browse(note_id).exists()
        if not note:
            return False
        note.done = True
        return self.ws_doc(note.doc_id.id)
