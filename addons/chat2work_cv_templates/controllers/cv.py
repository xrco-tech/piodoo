# -*- coding: utf-8 -*-
"""Adds the design choice to the guided form on the CV page."""

from odoo import http
from odoo.http import request

from odoo.addons.chat2work.controllers.cv import Chat2workCvController


class Chat2workCvTemplateController(Chat2workCvController):

    def _page(self, candidate, token, **extra):
        extra['cv_templates'] = request.env['chat2work.cv.template'].sudo().search([])
        return super()._page(candidate, token, **extra)

    @http.route()
    def cv_draft(self, token, **post):
        candidate = self._candidate(token)
        if candidate:
            candidate._c2w_set_cv_template(post.pop('cv_template', None))
        return super().cv_draft(token, **post)

    @http.route()
    def cv_build(self, token, **post):
        candidate = self._candidate(token)
        if candidate:
            candidate._c2w_set_cv_template(post.pop('cv_template', None))
        return super().cv_build(token, **post)
