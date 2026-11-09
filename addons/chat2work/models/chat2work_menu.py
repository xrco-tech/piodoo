# -*- coding: utf-8 -*-
"""Apps Chat2Work agents see.

Chat2Work agents who aren't admins only see the apps listed here (and
everything under them). Every other app is hidden from them, including ones
installed later. Other users are unaffected. Apps that aren't installed
are skipped.
"""

from odoo import api, models

AGENT_APPS = (
    'chat2work.menu_chat2work_root',         # Chat2Work
    'home-theme.menu_home_screen',           # Home screen
    'mail.menu_root_discuss',                # Discuss
    'calendar.mail_menu_calendar',           # Calendar
    'comm_whatsapp.menu_whatsapp_root',      # WhatsApp Light
    'contact_centre.menu_contact_centre_main',  # Contact Centre
    'cx_module.menu_cx_root',                # UCX
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        user = self.env.user
        if not user.has_group('chat2work.group_agent') or user.has_group('base.group_system'):
            return visible
        data = self.env['ir.model.data']
        allowed = {data._xmlid_to_res_id(x, raise_if_not_found=False) for x in AGENT_APPS} - {False, None}
        menus = self.sudo().with_context(**{'ir.ui.menu.full_list': True}).browse(visible)
        return {m.id for m in menus if m.parent_path and int(m.parent_path.split('/')[0]) in allowed}
