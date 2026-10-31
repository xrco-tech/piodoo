# -*- coding: utf-8 -*-
"""Candidates are for Chat2Work agents; other users, like MCP Sync, get listings only."""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workAgentAccess(TransactionCase):

    def setUp(self):
        super().setUp()
        self.staff = new_test_user(self.env, login='c2w_staff', groups='base.group_user')
        self.agent = new_test_user(self.env, login='c2w_agent', groups='chat2work.group_agent')
        self.cand = self.env['chat2work.candidate'].create({'name': 'Lindiwe', 'phone': '+27820000000'})
        self.listing = self.env['chat2work.listing'].create({'title': 'Cashier'})

    def test_other_staff_cannot_see_candidate_data(self):
        for model in ('chat2work.candidate', 'chat2work.callback.request', 'chat2work.interview.booking',
                      'chat2work.listing.match', 'chat2work.message'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.staff).search([])

    def test_agent_works_with_candidates(self):
        cand = self.cand.with_user(self.agent)
        cand.write({'stage': 'screened'})
        self.assertEqual(cand.stage, 'screened')

    def test_admin_is_an_agent(self):
        self.assertTrue(self.env.ref('base.user_admin').has_group('chat2work.group_agent'))

    def test_other_staff_can_still_manage_listings(self):
        Listing = self.env['chat2work.listing'].with_user(self.staff)
        listing = Listing.create({'title': 'Driver'})
        listing.write({'title': 'Delivery driver'})
        values = Listing.browse(self.listing.id).read(list(Listing.fields_get()))[0]
        self.assertEqual(values['suggested_count'], 0)
        self.assertNotIn('match_ids', values)

    def test_other_staff_can_read_jobs(self):
        job = self.env['chat2work.job'].create({'name': 'Picker'}).with_user(self.staff)
        values = job.read(list(job.fields_get()))[0]
        self.assertNotIn('slot_ids', values)

    def test_candidates_menu_hidden_from_other_staff(self):
        menus = self.env['ir.ui.menu'].with_user(self.staff).search([('name', '=', 'Chat2Work')])
        self.assertFalse(menus)
