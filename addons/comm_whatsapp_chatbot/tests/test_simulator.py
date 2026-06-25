# -*- coding: utf-8 -*-
"""Tests for the real-engine flow simulator (right-panel demo runner)."""

from unittest.mock import patch

from odoo.tests import common, tagged


def _mock_send_ok(*_args, **_kwargs):
    """Real-engine simulator NEVER calls send_whatsapp_message — its outbound
    is captured via env.context['sim_capture']. This mock is here just so the
    tests fail loudly if the capture path regresses and the real WA send fires
    accidentally."""
    return {'success': True, 'message_id': 'wamid.fake', 'error': None}


class SimFixtures(common.TransactionCase):
    """Caller bot + Sub bot wired via a subroutine jump with in/out variable
    mapping, plus a trigger word on the Caller so the simulator can fire the
    first turn against the real engine."""

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
        # Trigger so the engine knows what kind of inbound launches the bot.
        cls.env['whatsapp.chatbot.trigger'].create({
            'name': 'SIMSTART', 'chatbot_id': cls.caller.id,
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

        # Sub: Hi → Question → Save (static 42) → Bye → End
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

    def _sim(self, chatbot_id, state=None, user_input=None, contact_details=None):
        return self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=chatbot_id, session_state=state, user_input=user_input,
            contact_details=contact_details or {
                'name': 'Test Persona', 'mobile': '+27600000001',
            },
        )


# ──────────────────────────────────────────────────────────────────────────────
# First turn behaviour
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorFirstTurn(SimFixtures):

    def test_first_turn_emits_welcome_then_waits_on_question(self):
        r = self._sim(self.caller.id)
        texts = [b.get('body') or b.get('text', '') for b in r['bubbles']]
        self.assertTrue(any('Hello!' in t for t in texts),
                        f"Expected Welcome bubble, got: {texts}")
        self.assertTrue(any('What is your name?' in t for t in texts),
                        f"Expected question bubble, got: {texts}")
        self.assertFalse(r['terminate'])
        self.assertTrue(r['wait_for_input'])
        self.assertEqual(r['session_state']['current_step_id'], self.ask.id)

    def test_first_turn_creates_simulator_contact(self):
        r = self._sim(self.caller.id)
        contact_id = r['session_state']['contact_id']
        contact = self.env['whatsapp.chatbot.contact'].browse(contact_id)
        self.assertTrue(contact.exists())
        self.assertTrue(contact.is_simulator,
                        "Simulator contact must be flagged is_simulator=True")


# ──────────────────────────────────────────────────────────────────────────────
# Variables — source='answer' path that motivated the pivot
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorVariables(SimFixtures):

    def test_user_input_drives_substitution_across_jump(self):
        """User types 'Alice' at Ask Name → real engine writes user_name='Alice'
        on contact.variable_value_ids → jump's in-mapping copies into
        player_name → Sub Hi bubble renders 'Hi Alice'. This is the round-trip
        the pure walker got wrong in v1."""
        r1 = self._sim(self.caller.id)
        r2 = self._sim(self.caller.id, state=r1['session_state'], user_input='Alice')
        all_text = ' '.join((b.get('body') or b.get('text', '')) for b in r2['bubbles'])
        self.assertIn('Hi Alice', all_text,
                      f"Expected substituted Sub Hi bubble, got: {all_text!r}")

    def test_variable_values_are_persisted_with_simulator_flag(self):
        r1 = self._sim(self.caller.id)
        self._sim(self.caller.id, state=r1['session_state'], user_input='Alice')
        contact_id = r1['session_state']['contact_id']
        # user_name should be saved on the contact's variable_value_ids
        vals = self.env['whatsapp.chatbot.value'].search([
            ('contact_id', '=', contact_id),
            ('variable_id', '=', self.caller_name.id),
        ])
        self.assertEqual(len(vals), 1)
        self.assertEqual(vals[0].value, 'Alice')
        self.assertTrue(vals[0].is_simulator,
                        "Simulator variable_value rows must carry is_simulator=True")


# ──────────────────────────────────────────────────────────────────────────────
# Subroutine jump round-trip via the real engine
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorSubroutine(SimFixtures):

    def test_full_round_trip_through_real_engine(self):
        # Turn 1: Welcome + Ask Name (parked)
        r1 = self._sim(self.caller.id)
        # Turn 2: 'Bob' → Save → Jump → Sub Hi + Sub Question (parked in callee)
        r2 = self._sim(self.caller.id, state=r1['session_state'], user_input='Bob')
        self.assertEqual(r2['session_state']['current_step_id'], self.sub_question.id)
        self.assertEqual(len(r2['session_state']['call_stack']), 1,
                         "Subroutine frame should be on the contact's call stack")
        # Turn 3: '7' → Sub Save (final_score=42) → Sub Bye → Sub End (pop) →
        # Thanks (caller body with user_name+score) → Caller End
        r3 = self._sim(self.caller.id, state=r2['session_state'], user_input='7')
        all_text = ' '.join((b.get('body') or b.get('text', '')) for b in r3['bubbles'])
        self.assertIn('Thanks Bob', all_text,
                      f"Thanks bubble should mention Bob: {all_text!r}")
        self.assertIn('42', all_text,
                      f"Thanks should show out-mapped score 42: {all_text!r}")
        self.assertTrue(r3['terminate'])
        self.assertEqual(r3['session_state']['call_stack'], [])


# ──────────────────────────────────────────────────────────────────────────────
# Outbound capture — no real WA / SMS API calls
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorOutboundCapture(SimFixtures):

    def test_no_real_wa_send_during_simulation(self):
        """The capture mode short-circuits _send_message_via_channel before
        the WA HTTP call. send_whatsapp_message must never fire."""
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self._sim(self.caller.id)
        mock_send.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Analytics isolation — simulator records must not leak into counts
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorAnalyticsIsolation(SimFixtures):

    def test_simulator_runs_excluded_from_active_contact_count(self):
        before = self.caller.chatbot_contact_count
        self._sim(self.caller.id)
        self.caller.invalidate_recordset(['chatbot_contact_count'])
        self.assertEqual(self.caller.chatbot_contact_count, before,
                         "Simulator contact must not bump chatbot_contact_count")

    def test_simulator_runs_excluded_from_historical_count(self):
        before = self.caller.historical_contact_count
        self._sim(self.caller.id)
        # historical is a non-stored compute → re-read directly
        self.assertEqual(self.caller.historical_contact_count, before,
                         "Simulator contact must not bump historical_contact_count")

    def test_simulator_messages_excluded_from_message_count(self):
        before = self.caller.chatbot_message_count
        self._sim(self.caller.id)
        self.caller.invalidate_recordset(['chatbot_message_count'])
        self.assertEqual(self.caller.chatbot_message_count, before,
                         "Simulator messages must not bump chatbot_message_count")


# ──────────────────────────────────────────────────────────────────────────────
# Reset semantics
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorReset(SimFixtures):

    def test_starting_a_fresh_session_wipes_variables(self):
        r1 = self._sim(self.caller.id)
        self._sim(self.caller.id, state=r1['session_state'], user_input='Alice')
        contact_id = r1['session_state']['contact_id']
        # Now start a fresh session (no state passed) — values should be wiped.
        self._sim(self.caller.id)
        leftover = self.env['whatsapp.chatbot.value'].search_count([
            ('contact_id', '=', contact_id),
        ])
        self.assertEqual(leftover, 0,
                         "Fresh session must wipe previous variable values on the simulator contact")


# ──────────────────────────────────────────────────────────────────────────────
# Persona — contact_details keyed by mobile
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorPersona(SimFixtures):

    def test_persona_keyed_by_mobile_creates_distinct_contacts(self):
        """Two sessions with different mobiles → two independent simulator
        contacts, so personas don't share variable state."""
        r_alice = self._sim(self.caller.id, contact_details={
            'name': 'Alice', 'mobile': '+27600000010',
        })
        r_bob = self._sim(self.caller.id, contact_details={
            'name': 'Bob', 'mobile': '+27600000011',
        })
        self.assertNotEqual(
            r_alice['session_state']['contact_id'],
            r_bob['session_state']['contact_id'],
            "Different mobiles must yield different simulator contacts",
        )
        Contact = self.env['whatsapp.chatbot.contact']
        alice = Contact.browse(r_alice['session_state']['contact_id'])
        bob = Contact.browse(r_bob['session_state']['contact_id'])
        self.assertEqual(alice.partner_id.name, 'Alice')
        self.assertEqual(bob.partner_id.name, 'Bob')
        self.assertEqual(alice.partner_id.mobile, '+27600000010')
        self.assertEqual(bob.partner_id.mobile, '+27600000011')

    def test_same_mobile_reuses_existing_persona(self):
        """A second fresh session with the same mobile reuses the previous
        simulator partner+contact (handy for 'returning user' demos)."""
        r1 = self._sim(self.caller.id, contact_details={
            'name': 'Carla', 'mobile': '+27600000020',
        })
        r2 = self._sim(self.caller.id, contact_details={
            'name': 'Carla', 'mobile': '+27600000020',
        })
        self.assertEqual(
            r1['session_state']['contact_id'],
            r2['session_state']['contact_id'],
            "Same mobile must reuse the same simulator contact",
        )

    def test_rename_existing_persona(self):
        """Editing the name with an unchanged mobile relabels the existing
        simulator partner — no orphan partner spam."""
        r1 = self._sim(self.caller.id, contact_details={
            'name': 'Dee', 'mobile': '+27600000030',
        })
        contact_id = r1['session_state']['contact_id']
        self._sim(self.caller.id, contact_details={
            'name': 'Dee Renamed', 'mobile': '+27600000030',
        })
        c = self.env['whatsapp.chatbot.contact'].browse(contact_id)
        self.assertEqual(c.partner_id.name, 'Dee Renamed')

    def test_simulator_does_not_latch_onto_real_partner_with_matching_mobile(self):
        """If a real (non-simulator) partner happens to share the mobile,
        the simulator must NOT use them — it creates its own sim+<mobile>
        partner instead."""
        # Create a "real" partner with the same mobile but no sim marker.
        real = self.env['res.partner'].create({
            'name': 'Real Customer', 'mobile': '+27600000040',
            'email': 'customer@example.com',
        })
        r = self._sim(self.caller.id, contact_details={
            'name': 'Sim User', 'mobile': '+27600000040',
        })
        sim_contact = self.env['whatsapp.chatbot.contact'].browse(
            r['session_state']['contact_id'],
        )
        self.assertNotEqual(sim_contact.partner_id, real,
            "Simulator must not latch onto a real partner sharing the mobile",
        )
        self.assertTrue(sim_contact.partner_id.email.startswith('sim+'),
            "Simulator partner must use the sim+<mobile>@chatbot.local marker email",
        )

    def test_fallback_when_no_contact_details_given(self):
        """For backward compat: callers that omit contact_details still get a
        working per-uid persona (so any tests / scripts written against the
        v1 signature don't break)."""
        r = self.env['whatsapp.chatbot.message'].simulate_turn(
            chatbot_id=self.caller.id,
        )
        self.assertIn('contact_id', r['session_state'] or {})


# ──────────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'sim', 'post_install', '-at_install')
class TestSimulatorErrors(SimFixtures):

    def test_missing_bot_returns_error_bubble(self):
        r = self.env['whatsapp.chatbot.message'].simulate_turn(chatbot_id=999999)
        self.assertTrue(r['terminate'])
        self.assertEqual(r['bubbles'][0]['step_type'], 'error')
