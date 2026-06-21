# -*- coding: utf-8 -*-
"""Tests for the per-channel account models and account-aware routing."""

from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestWhatsAppAccountModel(common.TransactionCase):

    def test_unique_phone_number_id(self):
        Account = self.env['comm.whatsapp.account']
        Account.create({
            'name': 'A', 'phone_number': '+27693808741',
            'phone_number_id': '100000001', 'access_token': 'tok',
        })
        with self.assertRaises(Exception):
            Account.create({
                'name': 'B', 'phone_number': '+27693808742',
                'phone_number_id': '100000001', 'access_token': 'tok2',
            })

    def test_find_for_phone_number_id(self):
        Account = self.env['comm.whatsapp.account']
        a = Account.create({
            'name': 'Lookup A', 'phone_number': '+27693808743',
            'phone_number_id': '200000001', 'access_token': 'tok',
        })
        self.assertEqual(Account.find_for_phone_number_id('200000001'), a)
        self.assertFalse(Account.find_for_phone_number_id('does-not-exist'))
        self.assertFalse(Account.find_for_phone_number_id(''))

    def test_get_default_prefers_is_default(self):
        Account = self.env['comm.whatsapp.account']
        Account.create({
            'name': 'First', 'phone_number': '+27693808744',
            'phone_number_id': '300000001', 'sequence': 5,
        })
        b = Account.create({
            'name': 'Second', 'phone_number': '+27693808745',
            'phone_number_id': '300000002', 'sequence': 10, 'is_default': True,
        })
        self.assertEqual(Account.get_default(), b)


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestSmsAccountModel(common.TransactionCase):

    def test_unique_sender_per_provider(self):
        Account = self.env['comm.sms.account']
        Account.create({
            'name': 'A', 'sender_id': 'PIODOO', 'provider': 'infobip',
        })
        with self.assertRaises(Exception):
            Account.create({
                'name': 'B', 'sender_id': 'PIODOO', 'provider': 'infobip',
            })

    def test_find_for_sender_id(self):
        Account = self.env['comm.sms.account']
        a = Account.create({
            'name': 'Lookup',
            'sender_id': '27693808780',
            'provider': 'infobip',
        })
        self.assertEqual(Account.find_for_sender_id('27693808780'), a)


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestUssdAccountModel(common.TransactionCase):

    def test_unique_service_code(self):
        Account = self.env['comm.ussd.account']
        Account.create({'name': 'A', 'service_code': '*100#'})
        with self.assertRaises(Exception):
            Account.create({'name': 'B', 'service_code': '*100#'})

    def test_find_for_service_code(self):
        Account = self.env['comm.ussd.account']
        a = Account.create({'name': 'Demo USSD', 'service_code': '*101#'})
        self.assertEqual(Account.find_for_service_code('*101#'), a)


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestChatbotAccountWiring(common.TransactionCase):
    """The bot's sender_address mirrors whichever per-channel account is set,
    so the existing routing helpers (which match on sender_address) keep working."""

    def test_whatsapp_account_drives_sender_address(self):
        Account = self.env['comm.whatsapp.account']
        a = Account.create({
            'name': 'Driving', 'phone_number': '+27693808791',
            'phone_number_id': 'wa-id-1', 'access_token': 'tok',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'WA Account Driven Bot', 'channel': 'whatsapp',
            'whatsapp_account_id': a.id,
        })
        self.assertEqual(bot.sender_address, 'wa-id-1')

    def test_sms_account_drives_sender_address(self):
        a = self.env['comm.sms.account'].create({
            'name': 'Driving SMS', 'sender_id': 'PIODOO-SMS-1',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'SMS Account Driven Bot', 'channel': 'sms',
            'sms_account_id': a.id,
        })
        self.assertEqual(bot.sender_address, 'PIODOO-SMS-1')

    def test_ussd_account_drives_sender_address(self):
        a = self.env['comm.ussd.account'].create({
            'name': 'Driving USSD', 'service_code': '*200#',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'USSD Account Driven Bot', 'channel': 'ussd',
            'ussd_account_id': a.id,
        })
        self.assertEqual(bot.sender_address, '*200#')

    def test_channel_mismatch_account_does_not_leak_to_other_channel(self):
        """A SMS bot with a whatsapp_account_id set still resolves to empty
        sender_address because only the account matching `channel` is used."""
        wa = self.env['comm.whatsapp.account'].create({
            'name': 'Cross', 'phone_number': '+27693808792',
            'phone_number_id': 'wa-id-2', 'access_token': 'tok',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'Cross Bot', 'channel': 'sms',
            'whatsapp_account_id': wa.id,  # set but ignored — channel is sms
        })
        self.assertFalse(bot.sender_address,
                         "Only the account matching `channel` should set sender_address")


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestOutboundDispatchUsesAccount(common.TransactionCase):

    def test_whatsapp_send_passes_account_to_low_level_send(self):
        a = self.env['comm.whatsapp.account'].create({
            'name': 'Outbound', 'phone_number': '+27693808793',
            'phone_number_id': 'wa-id-out', 'access_token': 'tok-out',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'WA Outbound Bot', 'channel': 'whatsapp',
            'whatsapp_account_id': a.id, 'status': 'published',
        })
        step = self.env['whatsapp.chatbot.step'].create({
            'name': 'WA Root', 'chatbot_id': bot.id,
            'step_type': 'message', 'body_plain': 'hello',
        })
        with patch.object(
            type(self.env['whatsapp.message']),
            'send_whatsapp_message',
            return_value={'success': True, 'message_id': 'wamid.x', 'error': None},
        ) as mock_send:
            self.env['whatsapp.chatbot.message']._send_message_via_channel(
                chatbot=bot, step=step,
                recipient_phone='+27600000001', body='hello',
            )
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs.get('account'), a,
                         "Bot's whatsapp_account_id must be forwarded to send_whatsapp_message")

    def test_sms_send_writes_account_to_sms_record(self):
        a = self.env['comm.sms.account'].create({
            'name': 'SMS Out', 'sender_id': 'OUT-1',
        })
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'SMS Out Bot', 'channel': 'sms',
            'sms_account_id': a.id, 'status': 'published',
        })
        with patch.object(type(self.env['sms.sms']), '_send', return_value=None):
            self.env['whatsapp.chatbot.message']._send_via_sms(
                recipient_phone='+27600000002', body='hi sms', account=a,
            )
        sms = self.env['sms.sms'].search(
            [('number', '=', '+27600000002')], order='id desc', limit=1,
        )
        self.assertTrue(sms, "An sms.sms record should have been created")
        self.assertEqual(sms.account_id, a,
                         "The bot's SMS account must be written onto the sms.sms record")


@tagged('chatbot', 'accounts', 'post_install', '-at_install')
class TestUssdRoutingByAccount(common.TransactionCase):

    def test_resolve_ussd_chatbot_prefers_account_match(self):
        from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController
        # Two accounts on different codes; one bot pointing at each.
        a1 = self.env['comm.ussd.account'].create({
            'name': 'Code A', 'service_code': '*300#',
        })
        a2 = self.env['comm.ussd.account'].create({
            'name': 'Code B', 'service_code': '*301#',
        })
        bot1 = self.env['whatsapp.chatbot'].create({
            'name': 'USSD Bot A', 'channel': 'ussd',
            'ussd_account_id': a1.id, 'status': 'published',
        })
        bot2 = self.env['whatsapp.chatbot'].create({
            'name': 'USSD Bot B', 'channel': 'ussd',
            'ussd_account_id': a2.id, 'status': 'published',
        })
        # The controller's helper queries via request.env which isn't set up
        # in TransactionCase, so re-implement the path through the model layer.
        Bot = self.env['whatsapp.chatbot']
        Account = self.env['comm.ussd.account']
        acc = Account.find_for_service_code('*301#')
        resolved = Bot.search([
            ('channel', '=', 'ussd'),
            ('ussd_account_id', '=', acc.id),
            ('status', '=', 'published'),
        ], limit=1)
        self.assertEqual(resolved, bot2)

    def test_unmatched_service_code_falls_back_to_catch_all_bot(self):
        Bot = self.env['whatsapp.chatbot']
        catchall = Bot.create({
            'name': 'USSD Catchall', 'channel': 'ussd',
            'status': 'published',  # no ussd_account_id
        })
        Account = self.env['comm.ussd.account']
        acc = Account.find_for_service_code('*999-unknown#')
        self.assertFalse(acc)
        # When no account matches, the controller should fall back to a
        # published USSD bot with ussd_account_id NULL.
        resolved = Bot.search([
            ('channel', '=', 'ussd'),
            ('status', '=', 'published'),
            ('ussd_account_id', '=', False),
        ], limit=1)
        self.assertEqual(resolved, catchall)
