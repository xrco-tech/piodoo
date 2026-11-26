# -*- coding: utf-8 -*-
"""Shared links and PDF downloads for company docs.

`/library/shared/<key>` needs no sign-in: whoever has the link reads the doc.
The key is long and random, and a writer turns it off in the doc's
Properties, after which the link is gone for good.
"""
from odoo import http
from odoo.http import content_disposition, request

# The shared page runs no script and fetches nothing but pictures.
PAGE_HEADERS = [
    ('X-Robots-Tag', 'noindex, nofollow, noarchive'),
    ('Referrer-Policy', 'no-referrer'),
    ('Cache-Control', 'no-store'),
    ('Content-Security-Policy',
     "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'"),
]


class SedibaShareController(http.Controller):

    def _pdf(self, values):
        Workspace = request.env['sediba.workspace']
        pdf = Workspace._doc_page_pdf(values)
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', content_disposition(Workspace._doc_file_name(values))),
            ('X-Robots-Tag', 'noindex, nofollow, noarchive'),
            ('Cache-Control', 'no-store'),
        ])

    @http.route('/library/shared/<string:token>', type='http', auth='public', methods=['GET'], sitemap=False)
    def shared(self, token, **_kw):
        Workspace = request.env['sediba.workspace']
        values = Workspace._doc_page_shared(token)
        if not values:
            raise request.not_found()
        html = Workspace._doc_page_html(values, pdf_url='/library/shared/%s/pdf' % token)
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')] + PAGE_HEADERS)

    @http.route('/library/shared/<string:token>/pdf', type='http', auth='public', methods=['GET'], sitemap=False)
    def shared_pdf(self, token, **_kw):
        values = request.env['sediba.workspace']._doc_page_shared(token)
        if not values:
            raise request.not_found()
        return self._pdf(values)

    @http.route('/library/doc/<int:doc_id>/pdf', type='http', auth='user', methods=['GET'])
    def doc_pdf(self, doc_id, space='', version=0, **_kw):
        try:
            version = int(version or 0)
        except ValueError:
            version = 0
        values = request.env['sediba.workspace']._doc_page_for(doc_id, space or False, version)
        if not values:
            raise request.not_found()
        return self._pdf(values)
