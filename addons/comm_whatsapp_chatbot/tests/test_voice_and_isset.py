# -*- coding: utf-8 -*-
"""Tests for the voice channel constraints + is_set/is_not_set operators
on variable triggers (used by the slot-fill-anytime live-agent flow)."""

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged


@tagged('chatbot', 'voice', 'post_install', '-at_install')
class TestVoiceChannelConstraints(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.voice_bot = cls.env['whatsapp.chatbot'].create({
            'name': 'Voice Agent Script Bot',
            'channel': 'voice',
            'status': 'published',
        })

    def test_voice_rejects_interactive_button(self):
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Bad Buttons',
                'chatbot_id': self.voice_bot.id,
                'step_type': 'question_interactive',
                'wa_message_type': 'interactive_button',
            })

    def test_voice_rejects_interactive_flow(self):
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Bad Flow',
                'chatbot_id': self.voice_bot.id,
                'step_type': 'question_interactive',
                'wa_message_type': 'interactive_flow',
            })

    def test_voice_rejects_media_question_types(self):
        for st in ('question_image', 'question_video',
                   'question_audio', 'question_document'):
            with self.assertRaises(ValidationError,
                                   msg=f"{st} should be rejected on voice"):
                self.env['whatsapp.chatbot.step'].create({
                    'name': f'Bad {st}',
                    'chatbot_id': self.voice_bot.id,
                    'step_type': st,
                    'body_plain': 'irrelevant',
                })

    def test_voice_allows_text_question_and_message(self):
        # The two step types that matter for a voice script.
        m = self.env['whatsapp.chatbot.step'].create({
            'name': 'Greeting', 'chatbot_id': self.voice_bot.id,
            'step_type': 'message', 'body_plain': 'Welcome to support.',
        })
        q = self.env['whatsapp.chatbot.step'].create({
            'name': 'Ask Order Number', 'chatbot_id': self.voice_bot.id,
            'step_type': 'question_text',
            'body_plain': 'Could I have your order number please?',
            'parent_id': m.id,
        })
        self.assertTrue(m.id and q.id)

    def test_coaching_notes_and_crm_action_persist(self):
        s = self.env['whatsapp.chatbot.step'].create({
            'name': 'With Notes', 'chatbot_id': self.voice_bot.id,
            'step_type': 'message', 'body_plain': 'Greet the customer.',
            'coaching_notes': 'Empathy check: smile while speaking.',
            'crm_action': '[Open CRM contact card]',
        })
        self.assertEqual(s.coaching_notes, 'Empathy check: smile while speaking.')
        self.assertEqual(s.crm_action, '[Open CRM contact card]')


@tagged('chatbot', 'voice', 'post_install', '-at_install')
class TestIsSetOperator(common.TransactionCase):
    """is_set / is_not_set on trigger_variable_ids let authors skip a slot's
    'ask' step when the slot is already filled — central to slot-fill-anytime."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['whatsapp.chatbot.step']
        cls.bot = cls.env['whatsapp.chatbot'].create({
            'name': 'IsSet Bot', 'channel': 'whatsapp', 'status': 'published',
        })
        cls.env['whatsapp.chatbot.trigger'].create({
            'name': 'GO', 'chatbot_id': cls.bot.id,
        })
        cls.account_num = cls.env['whatsapp.chatbot.variable'].create({
            'name': 'account_number', 'data_type': 'text',
            'chatbot_id': cls.bot.id,
        })

        # Root → two children:
        #   "Skip Ask"    when account_number IS_SET
        #   "Ask Account" when account_number IS_NOT_SET (fallback)
        cls.root = Step.create({
            'name': 'Root', 'chatbot_id': cls.bot.id,
            'step_type': 'message', 'body_plain': 'Welcome.',
            'sequence': 1,
        })
        cls.skip = Step.create({
            'name': 'Skip Ask', 'chatbot_id': cls.bot.id,
            'step_type': 'message', 'body_plain': 'Looking up your account now.',
            'parent_id': cls.root.id, 'sequence': 10,
        })
        cls.env['whatsapp.chatbot.variable.trigger'].create({
            'step_id': cls.skip.id,
            'variable_id': cls.account_num.id,
            'operator': 'is_set',
        })
        cls.ask = Step.create({
            'name': 'Ask Account', 'chatbot_id': cls.bot.id,
            'step_type': 'message', 'body_plain': 'What is your account number?',
            'parent_id': cls.root.id, 'sequence': 20,
        })
        cls.env['whatsapp.chatbot.variable.trigger'].create({
            'step_id': cls.ask.id,
            'variable_id': cls.account_num.id,
            'operator': 'is_not_set',
        })

    def test_is_set_routes_to_skip_when_slot_pre_filled(self):
        """User has account_number already set → router picks the Skip branch
        and bypasses the Ask Account step entirely."""
        r = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id,
            contact_details={'name': 'Pre', 'mobile': '+27600000301'},
            initial_variables=[{'variable_id': self.account_num.id,
                                'value': 'ACC-77'}],
        )
        # Drive a follow-up to evaluate the children.
        r2 = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id, session_state=r['session_state'],
            user_input='anything',
        )
        all_text = ' '.join((b.get('body') or b.get('text', '')) for b in r2['bubbles'])
        self.assertIn('Looking up your account now', all_text,
                      "is_set branch should win when account_number has a value")
        self.assertNotIn('What is your account number', all_text)

    def test_is_not_set_routes_to_ask_when_slot_empty(self):
        """User has no account_number → router picks the Ask branch."""
        r = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id,
            contact_details={'name': 'Empty', 'mobile': '+27600000302'},
        )
        r2 = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id, session_state=r['session_state'],
            user_input='anything',
        )
        all_text = ' '.join((b.get('body') or b.get('text', '')) for b in r2['bubbles'])
        self.assertIn('What is your account number', all_text,
                      "is_not_set branch should win when account_number is empty")
        self.assertNotIn('Looking up your account now', all_text)

    def test_is_set_treats_empty_string_as_not_set(self):
        """Defensive: a contact value of '' should evaluate the same as missing —
        is_set returns False so the ask branch fires."""
        r = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id,
            contact_details={'name': 'Blank', 'mobile': '+27600000303'},
            initial_variables=[{'variable_id': self.account_num.id, 'value': '   '}],
        )
        r2 = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.bot.id, session_state=r['session_state'],
            user_input='anything',
        )
        all_text = ' '.join((b.get('body') or b.get('text', '')) for b in r2['bubbles'])
        # Whitespace-only is treated as not-set, so the ask branch wins.
        self.assertIn('What is your account number', all_text)


@tagged('chatbot', 'voice', 'post_install', '-at_install')
class TestPivotTextOnVariable(common.TransactionCase):

    def test_pivot_text_persists_on_variable(self):
        bot = self.env['whatsapp.chatbot'].create({
            'name': 'Pivot Bot', 'channel': 'voice',
        })
        v = self.env['whatsapp.chatbot.variable'].create({
            'name': 'order_number', 'data_type': 'text',
            'chatbot_id': bot.id,
            'pivot_text': 'I caught that order number, let me pull that up.',
        })
        self.assertEqual(
            v.pivot_text,
            'I caught that order number, let me pull that up.',
        )
