# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give every existing listing its employer record."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['chat2work.listing']._c2w_link_all_employers()
