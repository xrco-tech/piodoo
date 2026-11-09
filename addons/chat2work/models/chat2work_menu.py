# -*- coding: utf-8 -*-
"""Apps Chat2Work agents don't see.

These apps show their menus to every internal user. Chat2Work agents who
aren't admins don't need them, so they're hidden from them (with everything
under them). Others are unaffected. Apps that aren't installed are skipped.
"""

from odoo import api, models

HIDDEN_FOR_AGENTS = (
    'kiosk_receipt.menu_kiosk_root',                       # Kiosk
    'website.menu_website_configuration',                  # Website
    'hr.menu_hr_root',                                     # Employees
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',  # Dashboards
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        user = self.env.user
        if not user.has_group('chat2work.group_agent') or user.has_group('base.group_system'):
            return visible
        roots = [self.env['ir.model.data']._xmlid_to_res_id(x, raise_if_not_found=False) for x in HIDDEN_FOR_AGENTS]
        roots = [r for r in roots if r]
        if not roots:
            return visible
        hidden = set(self.sudo().with_context(**{'ir.ui.menu.full_list': True}).search(
            ['|'] * (len(roots) - 1) + [('parent_path', '=like', '%d/%%' % r) for r in roots]).ids)
        return visible - hidden
