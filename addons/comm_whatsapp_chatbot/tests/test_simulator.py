# -*- coding: utf-8 -*-
"""Tests for the ephemeral flow simulator (right-panel demo runner)."""

from odoo.tests import common, tagged


class SimFixtures(common.TransactionCase):
    """Two chatbots — Caller and Sub — wired with a subroutine jump so the
    tests can exercise variable mapping in & out across the jump."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['whatsapp.chatbot.step']
        Var = cls.env['whatsapp.chatbot.variable']

        cls.caller = cls.env['whatsapp.chatbot'].create({
            'name': 'Sim Caller', 'channel': 'whatsapp', 'status': 'published',
        })
        cls.sub = cls.env['whatsapp.chatbot'].create({
            'name': 'Sim Sub', 'channel': 'whatsapp', 'status': 'published',
        })

        # Caller: Welcome → Ask Name → Save → Jump (subroutine) → Thanks → End
        cls.welcome = Step.create({
            'name': 'Welcome', 'chatbot_id': cls.caller.id,
            'step_type': 'message', 'body_plain': 'Hello!', 'sequence': 1,
        })
        cls.ask = Step.create({
            'name': 'Ask Name', 'chatbot_id': cls.caller.id,
            'step_type': 'question_text', 'body_plain': 'What is your name?',
            'parent_id': cls.welcome.id, 'sequence': 10,
        })
        cls.caller_name = Var.create({
            'name': 'user_name', 'data_type': 'text',
            'chatbot_id': cls.caller.id,
        })
        cls.save = Step.create({
            'name': 'Save Name', 'chatbot_id': cls.caller.id,
            'step_type': 'set_variable', 'parent_id': cls.ask.id,
            'variable_id': cls.caller_name.id,
            'variable_data_source': 'answer', 'source_step_id': cls.ask.id,
        })

        # Sub: Hi → Question (text) → Save (static 42) → End
        cls.sub_hi = Step.create({
            'name': 'Sub Hi', 'chatbot_id': cls.sub.id,
            'step_type': 'message',
            'body_plain': 'Hi {{variables.player_name}}', 'sequence': 1,
        })
        cls.sub_question = Step.create({
            'name': 'Sub Question', 'chatbot_id': cls.sub.id,
            'step_type': 'question_text', 'body_plain': 'Pick a number',
            'parent_id': cls.sub_hi.id, 'sequence': 10,
        })
        cls.final_score = Var.create({
            'name': 'final_score', 'data_type': 'integer',
            'chatbot_id': cls.sub.id,
        })
        cls.sub_save = Step.create({
            'name': 'Sub Save', 'chatbot_id': cls.sub.id,
            'step_type': 'set_variable', 'parent_id': cls.sub_question.id,
            'variable_id': cls.final_score.id,
            'variable_data_source': 'static', 'variable_value': '42',
        })
        cls.sub_bye = Step.create({
            'name': 'Sub Bye', 'chatbot_id': cls.sub.id,
            'step_type': 'message', 'body_plain': 'Bye',
            'parent_id': cls.sub_save.id,
        })
        cls.sub_end = Step.create({
            'name': 'Sub End', 'chatbot_id': cls.sub.id,
            'step_type': 'end_flow', 'parent_id': cls.sub_bye.id,
        })

        # Subroutine variable mapping: user_name → player_name (in),
        # final_score → score (out)
        cls.player_name = Var.create({
            'name': 'player_name', 'data_type': 'text',
            'chatbot_id': cls.sub.id,
        })
        cls.caller_score = Var.create({
            'name': 'score', 'data_type': 'integer',
            'chatbot_id': cls.caller.id,
        })

        cls.jump = Step.create({
            'name': 'Jump To Sub', 'chatbot_id': cls.caller.id,
            'step_type': 'jump_to_flow', 'parent_id': cls.save.id,
            'target_chatbot_id': cls.sub.id, 'target_step_id': cls.sub_hi.id,
            'jump_mode': 'subroutine',
        })
        cls.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': cls.jump.id,
            'source_variable_id': cls.caller_name.id,
            'target_variable_id': cls.player_name.id,
            'direction': 'in',
        })
        cls.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': cls.jump.id,
            'source_variable_id': cls.caller_score.id,
            'target_variable_id': cls.final_score.id,
            'direction': 'out',
        })

        cls.thanks = Step.create({
            'name': 'Thanks', 'chatbot_id': cls.caller.id,
            'step_type': 'message',
            'body_plain': 'Thanks {{variables.user_name}} — score {{variables.score}}',
            'parent_id': cls.jump.id,
        })
        cls.caller_end = Step.create({
            'name': 'Caller End', 'chatbot_id': cls.caller.id,
            'step_type': 'end_flow', 'parent_id': cls.thanks.id,
        })

    def _sim(self, chatbot_id, state=None, user_input=None):
        return self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=chatbot_id, session_state=state, user_input=user_input,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Basic walker behaviour
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorBasic(SimFixtures):

    def test_first_turn_emits_welcome_then_question(self):
        result = self._sim(self.caller.id)
        texts = [b['text'] for b in result['bubbles']]
        self.assertIn('Hello!', texts)
        self.assertIn('What is your name?', texts)
        self.assertFalse(result['terminate'])
        self.assertTrue(result['wait_for_input'])
        self.assertEqual(result['session_state']['current_step_id'], self.ask.id)

    def test_simulator_is_ephemeral_no_db_writes(self):
        """No whatsapp.chatbot.message rows created during a sim turn."""
        before = self.env['whatsapp.chatbot.message'].search_count([])
        self._sim(self.caller.id)
        after = self.env['whatsapp.chatbot.message'].search_count([])
        self.assertEqual(before, after, "Simulator must not persist messages")

    def test_simulator_does_not_change_contact_state(self):
        """Sim turns must not touch any contact's last_chatbot/last_step."""
        partner = self.env['res.partner'].create({
            'name': 'X', 'mobile': '27600000099',
        })
        contact = self.env['whatsapp.chatbot.contact'].create({
            'partner_id': partner.id,
        })
        original_last_step = contact.last_step_id
        original_last_bot = contact.last_chatbot_id
        self._sim(self.caller.id)
        contact.invalidate_recordset()
        self.assertEqual(contact.last_step_id, original_last_step)
        self.assertEqual(contact.last_chatbot_id, original_last_bot)


# ──────────────────────────────────────────────────────────────────────────────
# set_variable + variable substitution
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorVariables(SimFixtures):

    def test_answer_key_is_recorded_on_step_transition(self):
        """When the user submits input while parked at a question step, the
        simulator stores it under __answer_step_<id> so downstream
        set_variable steps with source='answer' can find it. Regression for
        the screenshot where {{variables.user_name}} rendered literally."""
        r1 = self._sim(self.caller.id)
        state = r1['session_state']
        self.assertEqual(state['current_step_id'], self.ask.id)
        r2 = self._sim(self.caller.id, state=state, user_input='Alice')
        # __answer_step_<ask.id> should now hold 'Alice', AND the set_variable
        # 'Save Name' (source=answer, source_step_id=ask) should have copied
        # that into user_name itself.
        self.assertEqual(
            r2['session_state']['variables'].get(f'__answer_step_{self.ask.id}'),
            'Alice',
        )
        self.assertEqual(r2['session_state']['variables'].get('user_name'), 'Alice')

    def test_user_input_persists_in_state(self):
        r1 = self._sim(self.caller.id)
        state = r1['session_state']
        # Mock the user typing 'Alice' at the question.
        r2 = self._sim(self.caller.id, state=state, user_input='Alice')
        # The next bubble after Save Name (set_variable) is the Jump → Sub Hi
        # which renders {{player_name}} = 'Alice' via the in-mapping.
        sub_hi_text = next((b['text'] for b in r2['bubbles']
                            if 'Hi' in b['text']), '')
        self.assertIn('Alice', sub_hi_text,
                      "user_name should map to player_name via the jump's in-mapping")


# ──────────────────────────────────────────────────────────────────────────────
# Subroutine jump_to_flow round-trip
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorJumpSubroutine(SimFixtures):

    def test_full_round_trip(self):
        # Turn 1: Welcome + Ask Name
        r1 = self._sim(self.caller.id)
        # Turn 2: user answers 'Bob' → Save → Jump → Sub Hi + Sub Question
        r2 = self._sim(self.caller.id, state=r1['session_state'], user_input='Bob')
        self.assertEqual(r2['session_state']['current_step_id'], self.sub_question.id,
                         "After jump, walker should park at the sub bot's question")
        self.assertEqual(len(r2['session_state']['call_stack']), 1,
                         "Subroutine frame should be on the stack")
        # Turn 3: user answers '7' → Sub Save → Sub Bye → Sub End (pop) → Thanks → End
        r3 = self._sim(self.caller.id, state=r2['session_state'], user_input='7')
        texts = [b['text'] for b in r3['bubbles']]
        thanks = next((t for t in texts if 'Thanks Bob' in t), None)
        self.assertIsNotNone(thanks, "Thanks bubble should render with Bob + out-mapped score")
        self.assertIn('42', thanks, "Out-mapping should have carried final_score=42 into score")
        self.assertTrue(r3['terminate'], "Caller should have ended after the subroutine returned")
        self.assertEqual(r3['session_state']['call_stack'], [],
                         "Call stack should be empty after the round trip")


# ──────────────────────────────────────────────────────────────────────────────
# Error paths
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorErrors(SimFixtures):

    def test_missing_bot_returns_error(self):
        r = self.env['whatsapp.chatbot.message'].simulate_turn(chatbot_id=999999)
        self.assertTrue(r['terminate'])
        self.assertEqual(r['bubbles'][0]['step_type'], 'error')

    def test_bot_with_no_steps_returns_error(self):
        empty = self.env['whatsapp.chatbot'].create({
            'name': 'Empty Bot', 'channel': 'whatsapp',
        })
        r = self._sim(empty.id)
        self.assertTrue(r['terminate'])
        self.assertEqual(r['bubbles'][0]['step_type'], 'error')


# ──────────────────────────────────────────────────────────────────────────────
# Channel reporting
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorChannelReporting(common.TransactionCase):

    def test_returns_bot_channel(self):
        for ch in ('whatsapp', 'sms', 'ussd'):
            bot = self.env['whatsapp.chatbot'].create({
                'name': f'CHTest {ch}', 'channel': ch, 'status': 'published',
            })
            self.env['whatsapp.chatbot.step'].create({
                'name': f'Root {ch}', 'chatbot_id': bot.id,
                'step_type': 'message', 'body_plain': f'Hi from {ch}',
            })
            r = self.env['whatsapp.chatbot.message'].simulate_turn(chatbot_id=bot.id)
            self.assertEqual(r['channel'], ch)
