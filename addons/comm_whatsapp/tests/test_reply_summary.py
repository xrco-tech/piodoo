# -*- coding: utf-8 -*-
"""A tapped button or menu row is stored as what the person chose."""
from odoo.tests import common, tagged

VALUE = {'metadata': {'phone_number_id': '100200300', 'display_phone_number': '27100000000'},
         'contacts': [{'profile': {'name': 'Zzq Tapper'}, 'wa_id': '27820000077'}]}


def incoming(message_id, **content):
    return dict({'id': message_id, 'from': '27820000077', 'timestamp': '1762500000'}, **content)


def interactive(kind, **reply):
    return {'type': 'interactive', 'interactive': {'type': kind, kind: reply}}


@tagged('post_install', '-at_install')
class TestReplySummary(common.TransactionCase):

    def setUp(self):
        super().setUp()
        self.Message = self.env['whatsapp.message']

    def test_what_was_chosen(self):
        summary = self.Message._reply_summary
        self.assertEqual(summary(interactive('button_reply', id='yes', title='Yes, call me')), "Button: Yes, call me")
        self.assertEqual(summary(interactive('button_reply', id='yes')), "Button: yes")
        self.assertEqual(summary(interactive('list_reply', id='r1', title='Warehouse jobs')), "Menu choice: Warehouse jobs")
        self.assertEqual(summary(interactive('list_reply', id='r1', title='Warehouse jobs', description='Picking and packing')),
                         "Menu choice: Warehouse jobs (Picking and packing)")
        self.assertEqual(summary({'type': 'button', 'button': {'text': 'Stop', 'payload': 'STOP'}}), "Button: Stop")
        # What a form holds can be personal, so only that it was sent.
        self.assertEqual(summary(interactive('nfm_reply', name='flow', response_json='{"id_number": "9001015800087"}')),
                         "Form submitted")
        self.assertEqual(summary(interactive('something_new', x=1)), "Interactive: something_new")
        self.assertEqual(summary({'type': 'interactive'}), "Interactive: None")

    def test_call_permission(self):
        summary = lambda **reply: self.Message._reply_summary(interactive('call_permission_reply', **reply))
        self.assertEqual(summary(response='accept', is_permanent=False, expiration_timestamp=1763000000),
                         "Call permission: allowed")
        self.assertEqual(summary(response='accept', is_permanent=True), "Call permission: allowed permanently")
        self.assertEqual(summary(response='reject', response_source='user_action'), "Call permission: declined")
        self.assertEqual(summary(response='reject', response_source='automatic'), "Call permission: turned off by WhatsApp")

    def test_stored_on_the_message(self):
        entry = dict(VALUE, id='555')
        tapped = self.Message.create_from_webhook(
            incoming('wamid.tap1', **interactive('button_reply', id='menu', title='Main menu')), entry)
        self.assertEqual((tapped.message_type, tapped.interactive_type, tapped.message_body),
                         ('interactive', 'button_reply', "Button: Main menu"))
        # A quick-reply button on a template arrives as its own type.
        quick = self.Message.create_from_webhook(
            incoming('wamid.tap2', type='button', button={'text': 'Yes', 'payload': 'YES'}), entry)
        self.assertEqual((quick.message_type, quick.message_body), ('button', "Button: Yes"))
