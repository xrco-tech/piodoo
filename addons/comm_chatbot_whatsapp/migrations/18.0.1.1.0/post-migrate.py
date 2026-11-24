# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Every bot used the default WhatsApp account until now. Bots that run
    on WhatsApp are connected to it, so nothing stops answering."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['comm.bot']._connect_whatsapp_default()
