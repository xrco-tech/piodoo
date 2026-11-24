# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Every bot sent from the default SMS account until now. Bots that run
    on SMS are connected to it, so they send as before."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['comm.bot']._connect_sms_default()
