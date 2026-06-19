# -*- coding: utf-8 -*-
"""Tests for the USSD channel: constraint, session model, and render walker."""

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged


class UssdFixtures(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['whatsapp.chatbot.step']

        cls.ussd_bot = cls.env['whatsapp.chatbot'].create({
            'name': 'USSD Test Bot',
            'channel': 'ussd',
            'sender_address': '*123#',
            'status': 'published',
        })

        # Linear flow: Welcome → Question → End
        cls.welcome = Step.create({
            'name': 'Welcome',
            'chatbot_id': cls.ussd_bot.id,
            'step_type': 'message',
            'body_plain': 'Welcome to USSD',
            'sequence': 1,
        })
        cls.question = Step.create({
            'name': 'Question',
            'chatbot_id': cls.ussd_bot.id,
            'step_type': 'question_text',
            'body_plain': 'Pick an option',
            'parent_id': cls.welcome.id,
            'sequence': 10,
        })
        cls.option_a = Step.create({
            'name': 'Option A',
            'chatbot_id': cls.ussd_bot.id,
            'step_type': 'message',
            'body_plain': 'You chose A',
            'parent_id': cls.question.id,
            'sequence': 10,
        })
        cls.end = Step.create({
            'name': 'End',
            'chatbot_id': cls.ussd_bot.id,
            'step_type': 'end_flow',
            'parent_id': cls.option_a.id,
        })
        cls.answer_a = cls.env['whatsapp.chatbot.answer'].create({
            'value': '1',
            'step_id': cls.option_a.id,
            'operator': 'is_equal_to',
        })
        cls.option_a.write({'trigger_answer_ids': [(4, cls.answer_a.id)]})

        cls.partner = cls.env['res.partner'].create({
            'name': 'USSD Tester', 'mobile': '27600000077',
        })
        cls.contact = cls.env['whatsapp.chatbot.contact'].create({
            'partner_id': cls.partner.id,
        })


# ──────────────────────────────────────────────────────────────────────────────
# Constraints
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdConstraints(UssdFixtures):

    def test_media_question_rejected_on_ussd(self):
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Bad Image Step',
                'chatbot_id': self.ussd_bot.id,
                'step_type': 'question_image',
                'body_plain': 'Send image',
            })

    def test_interactive_button_rejected_on_ussd(self):
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Bad Buttons',
                'chatbot_id': self.ussd_bot.id,
                'step_type': 'question_interactive',
                'wa_message_type': 'interactive_button',
            })

    def test_question_text_allowed_on_ussd(self):
        step = self.env['whatsapp.chatbot.step'].create({
            'name': 'Text Question',
            'chatbot_id': self.ussd_bot.id,
            'step_type': 'question_text',
            'body_plain': 'Type something',
        })
        self.assertTrue(step.id)


# ──────────────────────────────────────────────────────────────────────────────
# Session model
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdSession(UssdFixtures):

    def test_find_or_create_creates_then_returns_existing(self):
        Session = self.env['whatsapp.chatbot.ussd.session']
        s1 = Session.find_or_create_for_inbound(
            session_id='ATUid_x1', service_code='*123#',
            phone_number='27600000077', chatbot=self.ussd_bot, contact=self.contact,
        )
        s2 = Session.find_or_create_for_inbound(
            session_id='ATUid_x1', service_code='*123#',
            phone_number='27600000077', chatbot=self.ussd_bot, contact=self.contact,
        )
        self.assertEqual(s1, s2)


# ──────────────────────────────────────────────────────────────────────────────
# Render walker
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdRender(UssdFixtures):

    def _new_session(self, session_id='ATUid_t1'):
        return self.env['whatsapp.chatbot.ussd.session'].create({
            'session_id': session_id,
            'service_code': '*123#',
            'phone_number': '27600000077',
            'chatbot_id': self.ussd_bot.id,
            'contact_id': self.contact.id,
        })

    def test_first_turn_walks_from_root_to_first_question(self):
        """Fresh session: walker should hit the question after the welcome."""
        session = self._new_session()
        body, terminate = self.env['whatsapp.chatbot.message'].render_ussd_session(
            session, user_input=None,
        )
        self.assertFalse(terminate, "Should keep session open at the question")
        self.assertIn("Welcome to USSD", body)
        self.assertIn("Pick an option", body)
        self.assertEqual(session.current_step_id, self.question,
                         "Walker should have parked at the question step")

    def test_matching_input_routes_to_option(self):
        """A '1' input matches Option A's trigger_answer and ends the flow."""
        session = self._new_session('ATUid_t2')
        # First turn
        self.env['whatsapp.chatbot.message'].render_ussd_session(session, user_input=None)
        # Second turn: user types 1
        body, terminate = self.env['whatsapp.chatbot.message'].render_ussd_session(
            session, user_input='1',
        )
        self.assertTrue(terminate, "Flow should end after Option A → End")
        self.assertIn("You chose A", body)

    def test_body_truncated_to_ussd_limit(self):
        """Bodies over 182 chars are truncated."""
        Step = self.env['whatsapp.chatbot.step']
        long_bot = self.env['whatsapp.chatbot'].create({
            'name': 'Long Bot', 'channel': 'ussd', 'status': 'published',
        })
        Step.create({
            'name': 'Long Root',
            'chatbot_id': long_bot.id,
            'step_type': 'message',
            'body_plain': 'x' * 300,
        })
        session = self.env['whatsapp.chatbot.ussd.session'].create({
            'session_id': 'ATUid_long', 'service_code': '*999#',
            'phone_number': '27600000077', 'chatbot_id': long_bot.id,
            'contact_id': self.contact.id,
        })
        body, terminate = self.env['whatsapp.chatbot.message'].render_ussd_session(
            session, user_input=None,
        )
        self.assertLessEqual(len(body), 182)
        self.assertTrue(body.endswith('…'))


# ──────────────────────────────────────────────────────────────────────────────
# Controller-level CON/END formatting
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'ussd', 'post_install', '-at_install')
class TestUssdControllerHelpers(common.TransactionCase):
    """Smoke tests of the helper functions inside the controller — keeps these
    behaviours pinned without spinning up the HTTP layer."""

    def test_latest_input_handles_empty(self):
        from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController
        self.assertEqual(UssdController._latest_input(''), '')
        self.assertEqual(UssdController._latest_input('1'), '1')
        self.assertEqual(UssdController._latest_input('1*Bob'), 'Bob')
        self.assertEqual(UssdController._latest_input('1*Bob*3'), '3')

    def test_format_ussd_prefix(self):
        from odoo.addons.comm_whatsapp_chatbot.controllers.ussd_inbound import UssdController
        self.assertEqual(UssdController._format_ussd('hi', False), 'CON hi')
        self.assertEqual(UssdController._format_ussd('bye', True), 'END bye')
