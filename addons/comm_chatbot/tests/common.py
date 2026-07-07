# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class ChatbotTestCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wa = cls.env.ref('comm_chatbot.channel_whatsapp')
        cls.sms = cls.env.ref('comm_chatbot.channel_sms')
        cls.ussd = cls.env.ref('comm_chatbot.channel_ussd')
        cls.voice = cls.env.ref('comm_chatbot.channel_voice')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Contact', 'mobile': '27831112222',
            'whatsapp_id': '27831112222',
        })
        cls.bot = cls.env['comm.bot'].create({
            'name': 'Test Bot',
            'engine_mode': 'shadow',   # never actually send
            'channel_ids': [(6, 0, [cls.wa.id, cls.sms.id, cls.ussd.id])],
            'default_language': 'en_US',
        })
        cls.step_greeting = cls.env['comm.bot.step'].create({
            'bot_id': cls.bot.id, 'name': 'greeting',
            'kind': 'message', 'body': 'Hello {{contact.first_name}}',
        })
        cls.step_menu = cls.env['comm.bot.step'].create({
            'bot_id': cls.bot.id, 'name': 'menu',
            'kind': 'menu', 'body': 'Choose:',
        })
        for label in ('Balance', 'Payments', 'Help'):
            cls.env['comm.bot.step.option'].create({
                'step_id': cls.step_menu.id, 'label': label, 'value': label,
            })
        cls.step_end = cls.env['comm.bot.step'].create({
            'bot_id': cls.bot.id, 'name': 'end',
            'kind': 'end', 'end_outcome': 'done',
        })
        cls.step_greeting.next_step_id = cls.step_menu.id
        cls.step_menu.next_step_id = cls.step_end.id
        cls.bot.entry_step_id = cls.step_greeting.id
