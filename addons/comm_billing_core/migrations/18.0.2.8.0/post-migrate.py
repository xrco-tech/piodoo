# -*- coding: utf-8 -*-
"""The app is shown as "Ops Costs" from this version.

The groups and the scheduled jobs are loaded once and never rewritten by an
update, so their names are changed here. A name someone has already changed
by hand is left alone.
"""
from odoo import SUPERUSER_ID, api

RENAMES = {
    'comm_billing_core.group_billing_administrator': (
        'Communication Billing Administrator', 'Ops Costs Administrator'),
    'comm_billing_core.group_billing_user': (
        'Communication Billing User', 'Ops Costs User'),
    'comm_billing_core.cron_comm_billing_budget_warnings': (
        'Comm Billing: budget warnings', 'Ops Costs: budget warnings'),
    'comm_billing_core.cron_comm_billing_fixed_fees': (
        'Comm Billing: charge fixed fees', 'Ops Costs: charge fixed fees'),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, (old, new) in RENAMES.items():
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and record.name == old:
            record.name = new
