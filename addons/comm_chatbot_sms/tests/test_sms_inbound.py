# -*- coding: utf-8 -*-
from odoo.tests import common, tagged


@tagged('comm_chatbot_sms', 'post_install', '-at_install')
class TestSmsInboundToInbox(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sms = cls.env['sms.sms']
        cls.Interaction = cls.env['comm.interaction']
        cls.channel = cls.env.ref('comm_chatbot.channel_sms')
        cls.partner = cls.env['res.partner'].create({'name': 'Thandi', 'mobile': '+27 82 555 0101'})

    def _interactions(self, partner):
        return self.Interaction.search([('conversation_id.partner_id', '=', partner.id)])

    def test_finds_contact_whatever_the_number_format(self):
        for number in ('27825550101', '+27825550101', '082 555 0101'):
            self.assertEqual(self.Sms._comm_partner_for_number(number), self.partner, number)
        self.assertFalse(self.Sms._comm_partner_for_number('27825550199'))
        self.assertFalse(self.Sms._comm_partner_for_number(''))

    def test_never_matches_the_company_contact(self):
        self.env.company.partner_id.mobile = '+27 82 555 0202'
        self.assertFalse(self.Sms._comm_partner_for_number('27825550202'))

    def test_inbound_sms_lands_in_the_inbox(self):
        interaction = self.Sms._comm_record_inbound(self.partner, '27825550101', 'Hello back', 'mo-1', 'Chat2Work')
        self.assertEqual(interaction.channel_id, self.channel)
        self.assertEqual(interaction.direction, 'inbound')
        self.assertEqual(interaction.status, 'received')
        self.assertEqual(interaction.raw_body, 'Hello back')
        self.assertEqual(interaction.conversation_id.partner_id, self.partner)

    def test_replies_join_the_open_conversation(self):
        first = self.Sms._comm_record_inbound(self.partner, '27825550101', 'one')
        second = self.Sms._comm_record_inbound(self.partner, '27825550101', 'two')
        self.assertEqual(first.conversation_id, second.conversation_id)
        self.assertEqual(len(self._interactions(self.partner)), 2)

    def test_reply_with_no_chatbot_is_kept(self):
        """The live gap: a reply that matches no SMS trigger used to be dropped."""
        if 'whatsapp.chatbot.message' not in self.env:
            self.skipTest('comm_whatsapp_chatbot not installed')
        self.env['whatsapp.chatbot.message'].process_incoming_sms_message(
            from_number='27825550101', message_text='Hello there', sms_message_id='112719314',
            to_number='Chat2Work')
        interactions = self._interactions(self.partner)
        self.assertEqual(interactions.mapped('raw_body'), ['Hello there'])
        # Matched the existing contact rather than creating a duplicate.
        self.assertEqual(self.env['res.partner'].search_count([('name', 'ilike', 'Contact 27825550101')]), 0)
