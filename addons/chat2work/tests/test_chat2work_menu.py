# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workAgentMenus(TransactionCase):

    def test_agents_do_not_see_hidden_apps(self):
        Menu = self.env['ir.ui.menu']
        root = Menu.create({'name': 'Other App'})
        child = Menu.create({'name': 'Other Child', 'parent_id': root.id,
                             'action': 'ir.actions.act_window,%d' % self.env.ref('contacts.action_contacts').id})
        self.env['ir.model.data'].create({'module': 'c2w_test', 'name': 'other_root', 'model': 'ir.ui.menu',
                                          'res_id': root.id})
        users = self.env['res.users'].with_context(no_reset_password=True)
        agent = users.create({'name': 'Agent', 'login': 'c2w_agent_menu',
                              'groups_id': [(6, 0, (self.env.ref('base.group_user')
                                                    | self.env.ref('chat2work.group_agent')).ids)]})
        plain = users.create({'name': 'Plain', 'login': 'c2w_plain_menu',
                              'groups_id': [(6, 0, self.env.ref('base.group_user').ids)]})
        with patch('odoo.addons.chat2work.models.chat2work_menu.HIDDEN_FOR_AGENTS',
                   ('c2w_test.other_root', 'not_installed.menu')):
            self.env.registry.clear_cache()
            agent_sees = Menu.with_user(agent)._visible_menu_ids()
            self.assertNotIn(root.id, agent_sees)
            self.assertNotIn(child.id, agent_sees)
            self.assertIn(self.env.ref('chat2work.menu_chat2work_root').id, agent_sees)
            plain_sees = Menu.with_user(plain)._visible_menu_ids()
            self.assertIn(root.id, plain_sees)
            self.assertIn(root.id, Menu.with_user(self.env.ref('base.user_admin'))._visible_menu_ids())
