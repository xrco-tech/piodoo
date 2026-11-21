# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPreviewContact(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['comm.bot.web.session']
        cls.Partner = cls.env['res.partner']
        cls.channel = cls.env['comm.channel'].search([('code', '=', 'web')], limit=1)
        cls.bot = cls.env['comm.bot'].create({'name': 'Web bot'})

    def test_previews_share_one_hidden_contact(self):
        before = self.Partner.with_context(active_test=False).search_count([])
        first = self.Session._preview_partner()
        second = self.Session._preview_partner()
        self.assertEqual(first, second)
        self.assertFalse(first.active, "it does not show in Contacts")
        self.assertEqual((first.name, first.mobile), ('Web preview', '+27600000000'))
        named = self.Session._preview_partner('Thabo', '+27600000009')
        self.assertEqual(named, first)
        self.assertEqual((first.name, first.mobile), ('Thabo', '+27600000009'))
        after = self.Partner.with_context(active_test=False).search_count([])
        self.assertEqual(after, before + 1)

    def _preview(self, partner):
        conversation = self.env['comm.conversation'].create({
            'partner_id': partner.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.channel.id,
            'outcome': '__preview_walker__'})
        return self.Session.create({
            'token': 'tok-%s' % partner.id, 'bot_id': self.bot.id,
            'conversation_id': conversation.id, 'partner_id': partner.id,
            'is_preview': True})

    def test_old_preview_contacts_are_archived_and_others_left(self):
        minted = self.Partner.create({'name': 'Web preview', 'mobile': '+27600000000'})
        self._preview(minted)
        stray = self.Partner.create({'name': 'Web preview', 'mobile': '+27600000000'})
        # Looks the same, but someone talked to a bot as this contact for real.
        talked = self.Partner.create({'name': 'Web preview', 'mobile': '+27600000000'})
        self.env['comm.conversation'].create({
            'partner_id': talked.id, 'bot_id': self.bot.id,
            'primary_channel_id': self.channel.id})
        # A real person who happens to be called the same, with their own number.
        namesake = self.Partner.create({'name': 'Web preview', 'mobile': '+27821234567'})
        visitor = self.Partner.create({'name': 'Web visitor'})

        archived = self.Session._archive_minted_preview_contacts()
        self.assertEqual(archived, minted | stray)
        self.assertFalse(minted.active)
        self.assertFalse(stray.active)
        self.assertTrue(talked.active)
        self.assertTrue(namesake.active)
        self.assertTrue(visitor.active)
        # Running it again changes nothing.
        self.assertFalse(self.Session._archive_minted_preview_contacts())
