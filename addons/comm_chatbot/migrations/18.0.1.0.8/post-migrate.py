# -*- coding: utf-8 -*-
"""WhatsApp and web chat show a header and a footer as their own lines. The
channel records are created once and never updated from their data file, so
the new switch is set here on databases that already have them."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['comm.channel'].with_context(active_test=False).search(
        [('code', 'in', ('whatsapp', 'web'))]
    ).write({'supports_header_footer': True})
