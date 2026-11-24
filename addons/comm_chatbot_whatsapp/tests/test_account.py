# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter


@tagged('post_install', '-at_install')
class TestWhatsappFlowAccount(TransactionCase):
    """A bot answers on the WhatsApp number it is connected to. Nothing is sent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.whatsapp.account']
        # The only accounts there are, so "the default" is one of ours.
        Account.search([]).write({'active': False})
        cls.main = Account.create({'name': 'Main line', 'phone_number': '+27 10 000 0001',
                                   'phone_number_id': 'test-pnid-1', 'is_default': True})
        cls.other = Account.create({'name': 'Second line', 'phone_number': '+27 10 000 0002',
                                    'phone_number_id': 'test-pnid-2'})
        cls.wa = cls.env.ref('comm_chatbot.channel_whatsapp')
        cls.bot = cls.env['comm.bot'].create({
            'name': 'Jobs', 'engine_mode': 'shadow', 'channel_ids': [(6, 0, cls.wa.ids)]})
        cls.env['comm.bot.trigger'].create({
            'bot_id': cls.bot.id, 'channel_id': cls.wa.id, 'kind': 'keyword', 'value': 'JOBS'})
        cls.adapter = get_adapter('whatsapp')()

    def _starts(self, account, body='jobs'):
        domain = [('bot_id.whatsapp_account_id', '=', account.id or 0)]
        return self.env['comm.bot.trigger'].with_context(
            comm_trigger_domain=domain).find_trigger('whatsapp', body).bot_id

    def test_a_message_starts_only_the_bot_on_its_number(self):
        self.assertFalse(self._starts(self.main), "not connected yet: nothing starts it")
        self.adapter.connect(self.env, self.bot, self.main.id, True)
        self.assertEqual(self._starts(self.main), self.bot)
        self.assertFalse(self._starts(self.other), "the same word on another number")
        self.assertFalse(self._starts(self.main, 'something else'))
        self.adapter.connect(self.env, self.bot, self.main.id, False)
        self.assertFalse(self._starts(self.main))

    def test_connecting_another_number_replaces_the_first(self):
        self.adapter.connect(self.env, self.bot, self.main.id, True)
        self.adapter.connect(self.env, self.bot, self.other.id, True)
        self.assertEqual(self.bot.whatsapp_account_id, self.other)
        options = {o['id']: o for o in self.adapter.connect_options(self.env, self.bot)}
        self.assertTrue(options[self.other.id]['connected'])
        self.assertFalse(options[self.main.id]['connected'])
        # Taking off a number it is not on changes nothing.
        self.adapter.connect(self.env, self.bot, self.main.id, False)
        self.assertEqual(self.bot.whatsapp_account_id, self.other)

    def test_lines_name_the_number_and_warn_when_nothing_starts_it(self):
        line = self.adapter.connections(self.env, self.bot)[0]
        self.assertFalse(line['ok'])
        self.assertIn('No WhatsApp number is connected', line['text'])
        self.adapter.connect(self.env, self.bot, self.main.id, True)
        lines = self.adapter.connections(self.env, self.bot)
        self.assertEqual(len(lines), 1, "connected and has a keyword: no warning")
        self.assertEqual((lines[0]['name'], lines[0]['address'], lines[0]['option_id']),
                         ('Main line', '+27 10 000 0001', self.main.id))
        self.bot.trigger_ids.unlink()
        lines = self.adapter.connections(self.env, self.bot)
        self.assertIn('No keyword starts this flow', lines[-1]['text'])

    def test_bots_already_on_whatsapp_keep_the_default_number(self):
        bare = self.env['comm.bot'].create({'name': 'No WhatsApp'})
        moved = self.env['comm.bot']._connect_whatsapp_default()
        self.assertIn(self.bot, moved)
        self.assertEqual(self.bot.whatsapp_account_id, self.main)
        self.assertFalse(bare.whatsapp_account_id)
        # A bot someone has since put on another number is left alone.
        self.bot.whatsapp_account_id = self.other
        self.env['comm.bot']._connect_whatsapp_default()
        self.assertEqual(self.bot.whatsapp_account_id, self.other)

    def test_a_copy_is_not_connected(self):
        self.bot.whatsapp_account_id = self.main
        self.assertFalse(self.bot.copy({'name': 'Jobs two'}).whatsapp_account_id)
