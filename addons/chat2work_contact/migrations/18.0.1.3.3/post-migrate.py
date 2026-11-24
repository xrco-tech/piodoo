# -*- coding: utf-8 -*-
"""Point the 'we tried to call you' SMS at the free-to-dial USSD code. The
template is loaded once (noupdate), so an installed database keeps the old
code unless it is changed here. A body someone has reworded is left alone
apart from the code itself."""

from odoo import SUPERUSER_ID, api

OLD_CODE = '*134*433*48#'
NEW_CODE = '*134*8615#'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref('chat2work_contact.sms_template_missed_call', raise_if_not_found=False)
    if template and OLD_CODE in (template.body or ''):
        template.body = template.body.replace(OLD_CODE, NEW_CODE)
