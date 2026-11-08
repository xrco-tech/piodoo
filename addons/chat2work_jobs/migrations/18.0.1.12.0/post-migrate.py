# -*- coding: utf-8 -*-
"""Read the experience asked for from every listing already in the database."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['chat2work.listing'].with_context(active_test=False).search([])._c2w_read_experience()
