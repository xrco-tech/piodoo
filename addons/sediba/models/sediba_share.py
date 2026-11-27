# -*- coding: utf-8 -*-
"""A company doc as one plain page: what a shared link shows and what
"Download PDF" prints.

The page is whole in itself (its styles are written into it), so it needs no
sign-in, no script and nothing fetched from the server, and the PDF maker can
turn it into a file as it stands. Diagrams print as numbered steps and visual
blocks as plain tables: the same facts the screen draws.
"""
import base64
import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import file_open

# A picture in a doc's text: /web/image/<id>, with or without the checksum
# and file name the editor adds.
PICTURE = re.compile(r'(<img\b[^>]*?\ssrc=")/web/image/(\d+)(?:-[0-9a-f]+)?(?:/[^"]*)?(")', re.I)
PICTURE_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
PICTURE_BYTES = 6 * 1024 * 1024


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
        for part in parts:
            if part.get('html'):
                part['html'] = self._doc_page_pictures(doc, part['html'])
        return {
            'name': source.name,
            'icon': self._doc_page_icon(doc),
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
    def _doc_page_icon(self, doc):
        """The doc's app icon written into the page, or False. The PNG beside
        the app's icon is used when there is one: the PDF maker draws it surely."""
        url = doc.sudo().icon_url
        if not url:
            return False
        path = url.lstrip('/')
        for name in (path.rsplit('.', 1)[0] + '.png', path):
            kind = {'png': 'image/png', 'svg': 'image/svg+xml'}.get(name.rsplit('.', 1)[-1].lower())
            if not kind:
                continue
            try:
                with file_open(name, 'rb', filter_ext=('.png', '.svg')) as icon:
                    return 'data:%s;base64,%s' % (kind, base64.b64encode(icon.read()).decode())
            except (OSError, ValueError):
                continue
        return False

    @api.model
    def _doc_page_pictures(self, doc, html):
        """The text with its pictures written into it, so the page needs
        nothing fetched: a reader with no sign-in, and the PDF maker, cannot
        ask the server for an attachment.

        Only a picture that belongs to this doc, or to no record at all (what
        the editor uploads), is written in. A picture attached to some other
        record stays a link, which shows nothing outside: a doc must not be a
        way to hand out another record's files."""
        ids = {int(match.group(2)) for match in PICTURE.finditer(html)}
        if not ids:
            return html
        found = {}
        for picture in self.env['ir.attachment'].sudo().browse(list(ids)).exists():
            own = picture.res_model == 'sediba.doc' and picture.res_id == doc.id
            loose = not picture.res_id and picture.res_model in (False, 'ir.ui.view', 'sediba.doc')
            if ((own or loose or picture.public) and picture.type == 'binary'
                    and picture.mimetype in PICTURE_TYPES and 0 < picture.file_size <= PICTURE_BYTES):
                found[picture.id] = 'data:%s;base64,%s' % (
                    picture.mimetype, base64.b64encode(picture.raw).decode())

        def written_in(match):
            data = found.get(int(match.group(2)))
            return match.group(1) + data + match.group(3) if data else match.group(0)
        return Markup(PICTURE.sub(written_in, html))

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
