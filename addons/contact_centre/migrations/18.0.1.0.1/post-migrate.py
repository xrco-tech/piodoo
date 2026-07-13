# -*- coding: utf-8 -*-

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """The group_contact_centre_agent/manager/admin implied_ids hierarchy
    added to contact_centre_security.xml in this version can't apply
    retroactively via a normal -u update, because those group records were
    originally created under noupdate="1" (protecting them from being
    overwritten). This migration applies the same implied_ids one time,
    directly, for databases that already had contact_centre installed
    before this hierarchy existed."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    def ref(xmlid):
        return env.ref(xmlid, raise_if_not_found=False)

    user_grp = ref('contact_centre.group_contact_centre_user')
    agent = ref('contact_centre.group_contact_centre_agent')
    manager = ref('contact_centre.group_contact_centre_manager')
    admin = ref('contact_centre.group_contact_centre_admin')

    if agent and user_grp and user_grp.id not in agent.implied_ids.ids:
        agent.write({'implied_ids': [(4, user_grp.id)]})
    if manager and agent and agent.id not in manager.implied_ids.ids:
        manager.write({'implied_ids': [(4, agent.id)]})
    if admin and manager and manager.id not in admin.implied_ids.ids:
        admin.write({'implied_ids': [(4, manager.id)]})
