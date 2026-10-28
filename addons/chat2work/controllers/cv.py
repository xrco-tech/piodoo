# -*- coding: utf-8 -*-
"""The candidate's CV page: /cv/<token>.

Public (the token is the credential), mobile-first and light on data. Three
ways to finish: upload an existing CV, build one with the guided form (we
render a standard PDF), or ask an agent for help. Nothing here shows or asks
for the ID number.
"""

import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_UPLOAD = 5 * 1024 * 1024
UPLOAD_TYPES = {
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.heic': 'image/heic',
}
MAX_ROWS = 3
TEXT_MAX = 600


def _clean(value, limit=200):
    return ' '.join((value or '').split())[:limit]


def _mask_phone(phone):
    digits = ''.join(c for c in phone or '' if c.isdigit())
    if digits.startswith('27') and len(digits) == 11:
        digits = '0' + digits[2:]
    return digits[:3] + '****' + digits[-3:] if len(digits) >= 7 else ''


class Chat2workCvController(http.Controller):

    def _candidate(self, token):
        return request.env['chat2work.candidate'].sudo()._c2w_find_by_token(token)

    def _page(self, candidate, token, **extra):
        values = {
            'candidate': candidate,
            'token': token,
            'first_name': (candidate.name or '').split(' ')[0] if candidate else '',
            'masked_phone': _mask_phone(candidate.phone) if candidate else '',
            'details': (candidate.cv_data or {}) if candidate else {},
            'rows': range(MAX_ROWS),
            'notice': extra.pop('notice', ''),
            'error': extra.pop('error', ''),
        }
        values.update(extra)
        status = 404 if not candidate else 200
        return request.render('chat2work.cv_page', values, status=status)

    @http.route('/cv/<string:token>', type='http', auth='public', methods=['GET'], sitemap=False)
    def cv_page(self, token, **kw):
        return self._page(self._candidate(token), token, notice=kw.get('done', ''))

    @http.route('/cv/<string:token>/upload', type='http', auth='public', methods=['POST'], sitemap=False)
    def cv_upload(self, token, cv_file=None, **kw):
        candidate = self._candidate(token)
        if not candidate:
            return self._page(candidate, token)
        if not cv_file or not getattr(cv_file, 'filename', ''):
            return self._page(candidate, token, error='Choose a file to upload.')
        ext = os.path.splitext(cv_file.filename)[1].lower()
        if ext not in UPLOAD_TYPES:
            return self._page(candidate, token, error='Upload a PDF, Word document or photo (JPG, PNG).')
        content = cv_file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            return self._page(candidate, token, error='That file is bigger than 5 MB. Try a smaller file or a photo.')
        if not content:
            return self._page(candidate, token, error='That file is empty. Try again.')
        name = 'CV upload%s' % ext
        candidate._c2w_store_cv_file(name, content, UPLOAD_TYPES[ext], 'uploaded')
        return request.redirect('/cv/%s?done=uploaded' % token, local=True)

    @http.route('/cv/<string:token>/build', type='http', auth='public', methods=['POST'], sitemap=False)
    def cv_build(self, token, **post):
        candidate = self._candidate(token)
        if not candidate:
            return self._page(candidate, token)
        details = {
            'full_name': _clean(post.get('full_name'), 80),
            'email': _clean(post.get('email'), 120),
            'town': _clean(post.get('town'), 80),
            'summary': _clean(post.get('summary'), TEXT_MAX),
            'skills': _clean(post.get('skills'), 300),
            'languages': _clean(post.get('languages'), 150),
            'licence': _clean(post.get('licence'), 40),
            'education': [], 'experience': [],
        }
        for i in range(MAX_ROWS):
            edu = {k: _clean(post.get('edu_%s_%d' % (k, i)), 120) for k in ('school', 'qualification', 'year')}
            if any(edu.values()):
                details['education'].append(edu)
            job = {k: _clean(post.get('job_%s_%d' % (k, i)), 120) for k in ('role', 'employer', 'dates')}
            job['duties'] = _clean(post.get('job_duties_%d' % i), 400)
            if any(job.values()):
                details['experience'].append(job)
        if not details['full_name']:
            return self._page(candidate, token, error='Please enter your full name.', details=details)
        try:
            candidate._c2w_build_cv(details)
        except Exception:
            _logger.exception("chat2work: CV build failed for candidate %s", candidate.id)
            return self._page(candidate, token, details=details,
                              error="We couldn't create your CV just now. Please try again, or ask us to help.")
        return request.redirect('/cv/%s?done=built' % token, local=True)

    @http.route('/cv/<string:token>/help', type='http', auth='public', methods=['POST'], sitemap=False)
    def cv_help(self, token, **kw):
        candidate = self._candidate(token)
        if not candidate:
            return self._page(candidate, token)
        if candidate.cv_state != 'help_requested':
            candidate._c2w_request_cv_help()
        return request.redirect('/cv/%s?done=help' % token, local=True)

    @http.route('/cv/<string:token>/download', type='http', auth='public', methods=['GET'], sitemap=False)
    def cv_download(self, token, **kw):
        candidate = self._candidate(token)
        att = candidate.cv_attachment_id.sudo() if candidate else None
        if not att or candidate.cv_state != 'built':
            return request.not_found()
        return request.make_response(att.raw, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', 'attachment; filename="%s"' % att.name.replace('"', '')),
        ])
