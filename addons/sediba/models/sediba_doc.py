# -*- coding: utf-8 -*-
"""Company docs: what we write about ourselves (About us, How we work, FAQ).

Kept apart from research on purpose. A finding has to be proven by outside
sources; a company doc is ours to say, so it has no sources and no "verified".
Instead it has an owner, it is a draft until someone publishes it, and it
carries a date by which it should be read again.

People outside the Library (the Reference inside an app) only ever see the last
published version. Editing a published doc changes nothing for them until it
is published again.

Like the rest of the Library, nothing here inherits mail.thread.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DOC_STATES = [
    ('draft', 'Draft'),
    ('published', 'Published'),
]

READ_AGAIN = [
    ('1', 'Every month'),
    ('3', 'Every 3 months'),
    ('6', 'Every 6 months'),
    ('12', 'Every year'),
]

# Changing one of these on a published doc leaves it with unpublished changes.
CONTENT_FIELDS = ('name', 'summary', 'body', 'flows')


class SedibaDoc(models.Model):
    _name = 'sediba.doc'
    _description = 'Company doc'
    _order = 'sequence, id'

    name = fields.Char(string="Title", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one('sediba.doc', string="Sits under", index=True, ondelete='restrict',
                                domain="[('parent_id', '=', False), ('id', '!=', id)]",
                                help="Leave empty for a doc of its own. A page sits under a doc.")
    child_ids = fields.One2many('sediba.doc', 'parent_id', string="Pages")
    summary = fields.Char(string="In one line", help="Shown under the title and on cards.")
    body = fields.Html(string="Text")
    flows = fields.Json(string="Flow diagrams", copy=True,
                        help="The diagrams in this doc, by the key of their block in the text.")
    question_ids = fields.One2many('sediba.doc.question', 'doc_id', string="Questions and answers", copy=True)
    owner_id = fields.Many2one('res.users', string="Owner", default=lambda self: self.env.user,
                               help="The person who keeps this doc right and is asked to read it again.")
    space_ids = fields.Many2many('sediba.space', string="Shown in",
                                 help="The apps whose Reference shows this doc once it is published.")
    topic_ids = fields.Many2many('sediba.topic', string="Related research",
                                 help="Research topics worth reading with this doc. Linked, never copied.")
    ai_allowed = fields.Boolean(string="Sidekick may answer from it", default=True,
                                help="Sidekick, the assistant your own staff use, may read the published "
                                     "version of this doc.")
    public_allowed = fields.Boolean(string="The public chatbot may answer from it",
                                    help="A chatbot that talks to people outside the company may read the "
                                         "published version of this doc. Leave it off for anything written "
                                         "for staff only.")
    read_again = fields.Selection(READ_AGAIN, string="Read again", required=True, default='3')
    state = fields.Selection(DOC_STATES, required=True, default='draft', readonly=True, copy=False, index=True)
    has_changes = fields.Boolean(string="Changed since it was published", readonly=True, copy=False)
    published_on = fields.Datetime(readonly=True, copy=False)
    last_read_on = fields.Date(string="Last read through", readonly=True, copy=False,
                               help="The day it was published or confirmed as still right.")
    read_again_by = fields.Date(compute='_compute_read_again_by', store=True)
    version_ids = fields.One2many('sediba.doc.version', 'doc_id', string="Published versions")
    note_ids = fields.One2many('sediba.doc.note', 'doc_id', string="Notes to the owner")

    @api.depends('state', 'last_read_on', 'read_again')
    def _compute_read_again_by(self):
        for doc in self:
            if doc.state == 'published' and doc.last_read_on:
                doc.read_again_by = doc.last_read_on + relativedelta(months=int(doc.read_again or 3))
            else:
                doc.read_again_by = False

    @api.constrains('parent_id')
    def _check_parent(self):
        if self._has_cycle():
            raise ValidationError(_("A doc cannot sit under itself."))
        for doc in self:
            if doc.parent_id.parent_id:
                raise ValidationError(_(
                    "'%s' is already a page under another doc. Pages go one level deep.",
                    doc.parent_id.name))
            if doc.parent_id and doc.child_ids:
                raise ValidationError(_(
                    "'%s' has pages of its own, so it cannot become a page.", doc.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # A new page starts out shown where its parent is shown.
            if vals.get('parent_id') and 'space_ids' not in vals:
                parent = self.browse(vals['parent_id'])
                vals['space_ids'] = [(6, 0, parent.space_ids.ids)]
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('sediba_publishing') and any(key in vals for key in CONTENT_FIELDS):
            changed = self.filtered(lambda d: d.state == 'published' and any(
                key in vals and (vals[key] or False) != (d[key] or False) for key in CONTENT_FIELDS))
            if changed:
                super(SedibaDoc, changed).write(dict(vals, has_changes=True))
            return super(SedibaDoc, self - changed).write(vals) if self - changed else True
        return super().write(vals)

    # ── Publishing ───────────────────────────────────────────────────────────

    def _latest(self):
        """The newest published version. Sorted here: a version made in this
        same request is not yet in order in the cache."""
        self.ensure_one()
        return self.version_ids.sorted('number', reverse=True)[:1]

    def _published(self):
        """The version people outside the Library see, or nothing for a draft."""
        self.ensure_one()
        return self._latest() if self.state == 'published' else self.env['sediba.doc.version']

    def action_publish(self):
        today = fields.Date.context_today(self)
        for doc in self:
            self.env['sediba.doc.version'].create({
                'doc_id': doc.id,
                'number': (doc._latest().number or 0) + 1,
                'name': doc.name,
                'summary': doc.summary,
                'body': doc.body,
                'flows': doc.flows or {},
                'questions': [{'name': q.name, 'answer': q.answer or ''} for q in doc.question_ids],
                'published_on': fields.Datetime.now(),
                'published_by': self.env.user.name,
            })
            doc.with_context(sediba_publishing=True).write({
                'state': 'published', 'has_changes': False,
                'published_on': fields.Datetime.now(), 'last_read_on': today})
        return True

    def action_take_down(self):
        """Back to a draft: the apps stop showing it. Its versions are kept."""
        self.with_context(sediba_publishing=True).write({'state': 'draft', 'has_changes': False})
        return True

    def action_read_again(self):
        """The owner read it through and it is still right."""
        self.filtered(lambda d: d.state == 'published').last_read_on = fields.Date.context_today(self)
        return True

    def action_restore(self, version):
        """Bring a published version back as the working text. Nothing shows
        outside the Library until it is published again."""
        self.ensure_one()
        version = version.filtered(lambda v: v.doc_id == self)
        if not version:
            return False
        self.question_ids.unlink()
        self.write({
            'name': version.name, 'summary': version.summary, 'body': version.body,
            'flows': version.flows or {},
            'question_ids': [(0, 0, {'sequence': index, 'name': q.get('name'), 'answer': q.get('answer')})
                             for index, q in enumerate(version.questions or [])],
        })
        if self.state == 'published':
            self.has_changes = True
        return True

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        if 'name' not in (default or {}):
            for doc, vals in zip(self, vals_list):
                vals['name'] = _("%s (copy)", doc.name)
        return vals_list


class SedibaDocQuestion(models.Model):
    _name = 'sediba.doc.question'
    _description = 'Question and answer in a company doc'
    _order = 'doc_id, sequence, id'

    doc_id = fields.Many2one('sediba.doc', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Question", required=True)
    answer = fields.Text()

    def _touch(self, docs):
        docs.filtered(lambda d: d.state == 'published' and not d.has_changes).sudo().has_changes = True

    @api.model_create_multi
    def create(self, vals_list):
        questions = super().create(vals_list)
        self._touch(questions.doc_id)
        return questions

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals or 'answer' in vals or 'sequence' in vals:
            self._touch(self.doc_id)
        return result

    def unlink(self):
        docs = self.doc_id
        result = super().unlink()
        self._touch(docs)
        return result


class SedibaDocVersion(models.Model):
    """One published version of a doc, kept whole so it can be shown and
    restored. The newest one is what the apps show."""
    _name = 'sediba.doc.version'
    _description = 'Published version of a company doc'
    _order = 'number desc, id desc'

    doc_id = fields.Many2one('sediba.doc', required=True, index=True, ondelete='cascade')
    number = fields.Integer(required=True)
    name = fields.Char(string="Title", required=True)
    summary = fields.Char()
    body = fields.Html()
    flows = fields.Json()
    questions = fields.Json()
    published_on = fields.Datetime(required=True)
    published_by = fields.Char()


class SedibaDocNote(models.Model):
    """'Tell the owner': a reader says a doc is wrong or missing something."""
    _name = 'sediba.doc.note'
    _description = 'Note to the owner of a company doc'
    _order = 'done, id desc'

    doc_id = fields.Many2one('sediba.doc', required=True, index=True, ondelete='cascade')
    name = fields.Text(string="Note", required=True)
    author = fields.Char(string="From")
    space = fields.Char(string="Sent from")
    done = fields.Boolean(string="Dealt with")
