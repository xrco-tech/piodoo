# -*- coding: utf-8 -*-
"""A company doc as one plain page: what a shared link shows and what
"Download PDF" prints.

The page is whole in itself (its styles are written into it), so it needs no
sign-in, no script and nothing fetched from the server, and the PDF maker can
turn it into a file as it stands. Diagrams print as numbered steps and visual
blocks as plain tables: the same facts the screen draws.
"""
import re

from odoo import _, api, fields, models


class SedibaShare(models.AbstractModel):
    _inherit = 'sediba.workspace'

    @api.model
    def _doc_page_values(self, doc, source, space=False, outside=False):
        """What the plain page draws for `doc`, read from `source`: the doc
        itself (its working text) or one of its published versions."""
        if source._name == 'sediba.doc.version':
            questions = [{'name': q.get('name', ''), 'answer': q.get('answer', '')} for q in source.questions or []]
            updated = source.published_on
        else:
            questions = [{'name': q.name, 'answer': q.answer or ''} for q in source.question_ids]
            updated = source.write_date
        # Outside the Library an empty visual block is left out, as in an app.
        parts = self._doc_parts(source.body, source.flows, space or (outside and '-') or False)
        return {
            'name': source.name,
            'summary': source.summary or '',
            'parts': parts,
            'questions': questions,
            'updated': self._date(updated),
            'today': self._date(fields.Date.context_today(self)),
            'owner': False if outside else doc.owner_id.name or '',
            'company': self.env.company.name,
            'empty': not parts and not questions,
        }

    @api.model
    def _doc_page_for(self, doc_id, space=False, version_id=False):
        """The page for someone signed in: the same text `ws_doc` would show
        them, or False when they may not see the doc."""
        doc = self.env['sediba.doc'].browse(doc_id).exists() & self._docs(space)
        if not doc:
            return False
        version = doc._published() if space else doc.version_ids.filtered(lambda v: v.id == version_id)
        return self._doc_page_values(doc, version or doc, space)

    @api.model
    def _doc_page_shared(self, token):
        """The page behind a shared link, or False when the link is unknown
        or was turned off. Called for someone who is not signed in, so this
        is the one place that decides what they may read."""
        if not token or len(token) < 20:
            return False
        doc = self.env['sediba.doc'].sudo().search([('share_token', '=', token)], limit=1)
        if not doc:
            return False
        return self.sudo()._doc_page_values(doc, doc._shown_outside(), outside=True)

    @api.model
    def _doc_page_html(self, values, pdf_url=False, for_pdf=False):
        return self.env['ir.qweb'].sudo()._render('sediba.doc_page', dict(
            values, pdf_url=pdf_url, for_pdf=for_pdf))

    @api.model
    def _doc_page_pdf(self, values):
        html = self._doc_page_html(values, for_pdf=True)
        return self.env['ir.actions.report'].sudo()._run_wkhtmltopdf(
            [str(html)], specific_paperformat_args={'data-report-margin-top': 14, 'data-report-header-spacing': 0})

    @api.model
    def _doc_file_name(self, values):
        name = re.sub(r'[^\w\- ]+', ' ', values['name'] or '').strip()
        return "%s.pdf" % (re.sub(r'\s+', ' ', name)[:80] or _("Doc"))
