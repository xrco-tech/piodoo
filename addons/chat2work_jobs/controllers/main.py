# -*- coding: utf-8 -*-
"""Short job links in alerts: /j/<token> counts the open and goes to the employer."""

import re

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request

from ..models.chat2work_job_alert import TOKEN_ALPHABET, TOKEN_LENGTH


class Chat2workJobLink(http.Controller):

    @http.route('/j/<string:token>', type='http', auth='public', methods=['GET'], sitemap=False)
    def job_link(self, token, **kwargs):
        token = (token or '').upper()
        if len(token) != TOKEN_LENGTH or set(token) - set(TOKEN_ALPHABET):
            raise NotFound()
        match = request.env['chat2work.listing.match'].sudo().search([('link_token', '=', token)], limit=1)
        url = (match.listing_id.apply_url or '').strip()
        if not match or not url:
            raise NotFound()
        if not re.match(r'^https?://', url, re.I):
            if re.match(r'^[a-z][a-z0-9+.-]*:', url, re.I):  # mailto:, javascript: and the like
                raise NotFound()
            url = 'https://' + url
        match.write({'open_count': match.open_count + 1, 'opened_at': match.opened_at or fields.Datetime.now()})
        return request.redirect(url, code=302, local=False)
