# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter


@tagged('comm_chatbot_sms', 'post_install', '-at_install')
class TestSmsFlowAccount(TransactionCase):
    """A bot sends its SMS from the account it is connected to. Nothing is sent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env['comm.sms.account']
        Account.search([]).write({'active': False})
        cls.main = Account.create({'name': 'Main sender', 'sender_id': 'TESTMAIN', 'is_default': True})
        cls.other = Account.create({'name': 'Second sender', 'sender_id': 'TESTTWO'})
        cls.sms = cls.env.ref('comm_chatbot.channel_sms')
        cls.bot = cls.env['comm.bot'].create({
            'name': 'Reminders', 'channel_ids': [(6, 0, cls.sms.ids)]})
        cls.adapter = get_adapter('sms')()

    def test_connect_and_disconnect(self):
        first = self.adapter.connections(self.env, self.bot)[0]
        self.assertFalse(first['ok'])
        self.assertIn('default account', first['text'])
        self.adapter.connect(self.env, self.bot, self.other.id, True)
        line = self.adapter.connections(self.env, self.bot)[0]
        self.assertEqual((line['name'], line['address'], line['option_id']),
                         ('Second sender', 'TESTTWO', self.other.id))
        options = {o['id']: o['connected'] for o in self.adapter.connect_options(self.env, self.bot)}
        self.assertEqual((options[self.other.id], options[self.main.id]), (True, False))
        self.adapter.connect(self.env, self.bot, self.other.id, False)
        self.assertFalse(self.bot.sms_account_id)

    def test_bots_already_on_sms_keep_the_default_sender(self):
        bare = self.env['comm.bot'].create({'name': 'No SMS'})
        self.env['comm.bot']._connect_sms_default()
        self.assertEqual(self.bot.sms_account_id, self.main)
        self.assertFalse(bare.sms_account_id)
