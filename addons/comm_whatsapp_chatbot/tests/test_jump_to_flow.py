# -*- coding: utf-8 -*-
"""Tests for the jump_to_flow step type and subroutine call stack."""
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged


def _mock_send_ok(*_args, **_kwargs):
    return {'success': True, 'message_id': 'wamid.jump'}


class JumpFixtures(common.TransactionCase):
    """Two chatbots: bot_caller has a Jump step into bot_callee."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['whatsapp.chatbot.step']
        Chatbot = cls.env['whatsapp.chatbot']
        Var = cls.env['whatsapp.chatbot.variable']

        cls.bot_caller = Chatbot.create({'name': 'Caller Bot', 'status': 'published'})
        cls.bot_callee = Chatbot.create({'name': 'Callee Bot', 'status': 'published'})

        # Caller flow:
        #   caller_root (message)
        #     └── caller_jump (jump_to_flow → callee_root)
        #           └── caller_after_return (message)  -- only used in subroutine mode
        cls.caller_root = Step.create({
            'name': 'Caller Root',
            'chatbot_id': cls.bot_caller.id,
            'step_type': 'message',
            'body_plain': 'Welcome, calling subroutine.',
            'sequence': 1,
        })
        cls.caller_jump = Step.create({
            'name': 'Jump Step',
            'chatbot_id': cls.bot_caller.id,
            'step_type': 'jump_to_flow',
            'target_chatbot_id': cls.bot_callee.id,
            'jump_mode': 'one_way',
            'parent_id': cls.caller_root.id,
            'sequence': 10,
        })
        cls.caller_after_return = Step.create({
            'name': 'After Return',
            'chatbot_id': cls.bot_caller.id,
            'step_type': 'message',
            'body_plain': 'Welcome back.',
            'parent_id': cls.caller_jump.id,
            'sequence': 10,
        })

        # Callee flow:
        #   callee_root (message)
        #     └── callee_end (end_flow)
        cls.callee_root = Step.create({
            'name': 'Callee Root',
            'chatbot_id': cls.bot_callee.id,
            'step_type': 'message',
            'body_plain': 'Inside callee.',
            'sequence': 1,
        })
        cls.callee_end = Step.create({
            'name': 'Callee End',
            'chatbot_id': cls.bot_callee.id,
            'step_type': 'end_flow',
            'body_plain': '',
            'parent_id': cls.callee_root.id,
            'sequence': 10,
        })

        # Variables on each bot (same logical names, distinct records — that's
        # exactly the situation the explicit mapping is designed for).
        cls.caller_name_var = Var.create({
            'name': 'name', 'data_type': 'text', 'chatbot_id': cls.bot_caller.id,
        })
        cls.caller_result_var = Var.create({
            'name': 'result', 'data_type': 'text', 'chatbot_id': cls.bot_caller.id,
        })
        cls.callee_name_var = Var.create({
            'name': 'name', 'data_type': 'text', 'chatbot_id': cls.bot_callee.id,
        })
        cls.callee_result_var = Var.create({
            'name': 'result', 'data_type': 'text', 'chatbot_id': cls.bot_callee.id,
        })

        cls.partner = cls.env['res.partner'].create({
            'name': 'Jumper', 'mobile': '27600000099',
        })
        cls.contact = cls.env['whatsapp.chatbot.contact'].create({
            'partner_id': cls.partner.id,
        })

    def _make_incoming(self, step, body='hello', chatbot=None):
        return self.env['whatsapp.chatbot.message'].create({
            'contact_id': self.contact.id,
            'chatbot_id': (chatbot or step.chatbot_id).id,
            'step_id': step.id,
            'mobile_number': '27600000099',
            'message_plain': body,
            'type': 'incoming',
        })

    def _set_value(self, contact, variable, value):
        existing = self.env['whatsapp.chatbot.value'].search([
            ('contact_id', '=', contact.id),
            ('variable_id', '=', variable.id),
        ], limit=1)
        if existing:
            existing.value = value
        else:
            self.env['whatsapp.chatbot.value'].create({
                'contact_id': contact.id,
                'variable_id': variable.id,
                'value': value,
            })

    def _get_value(self, contact, variable):
        rec = self.env['whatsapp.chatbot.value'].search([
            ('contact_id', '=', contact.id),
            ('variable_id', '=', variable.id),
        ], limit=1)
        return rec.value if rec else None


# ──────────────────────────────────────────────────────────────────────────────
# Model-layer constraints
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestJumpToFlowConstraints(JumpFixtures):

    def test_jump_step_requires_target_chatbot(self):
        """jump_to_flow without target_chatbot_id raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Bad Jump',
                'chatbot_id': self.bot_caller.id,
                'step_type': 'jump_to_flow',
            })

    def test_target_step_must_belong_to_target_chatbot(self):
        """target_step_id from a different chatbot is rejected."""
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step'].create({
                'name': 'Mismatched Jump',
                'chatbot_id': self.bot_caller.id,
                'step_type': 'jump_to_flow',
                'target_chatbot_id': self.bot_callee.id,
                'target_step_id': self.caller_root.id,  # belongs to bot_caller, not bot_callee
            })

    def test_mapping_source_must_match_caller_chatbot(self):
        """Mapping row whose source variable is from the wrong bot fails."""
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step.var.mapping'].create({
                'step_id': self.caller_jump.id,
                'source_variable_id': self.callee_name_var.id,  # wrong bot
                'target_variable_id': self.callee_name_var.id,
                'direction': 'in',
            })

    def test_mapping_target_must_match_target_chatbot(self):
        """Mapping row whose target variable is from the wrong bot fails."""
        with self.assertRaises(ValidationError):
            self.env['whatsapp.chatbot.step.var.mapping'].create({
                'step_id': self.caller_jump.id,
                'source_variable_id': self.caller_name_var.id,
                'target_variable_id': self.caller_name_var.id,  # wrong bot
                'direction': 'in',
            })


# ──────────────────────────────────────────────────────────────────────────────
# Runtime: one-way jump
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestOneWayJump(JumpFixtures):

    def test_one_way_switches_chatbot_and_fires_entry_step(self):
        """One-way jump replaces the active chatbot and sends the callee's entry step."""
        self.caller_jump.jump_mode = 'one_way'
        msg = self._make_incoming(self.caller_jump, body='go')

        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)

        mock_send.assert_called()
        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.last_chatbot_id, self.bot_callee)
        # callee_root has a single end_flow child → no further auto-advance
        # Last step should be callee_root (it was sent) or the end after a pop.
        self.assertIn(self.contact.last_step_id, (self.callee_root, self.callee_end))

    def test_one_way_does_not_push_call_stack(self):
        """One-way jump must not push a frame on the call stack."""
        self.caller_jump.jump_mode = 'one_way'
        msg = self._make_incoming(self.caller_jump, body='go')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.call_stack or [], [],
                         "One-way jump must not push a frame")

    def test_default_entry_step_is_target_root(self):
        """When target_step_id is empty, runtime resolves to the target's root step."""
        self.caller_jump.jump_mode = 'one_way'
        self.caller_jump.target_step_id = False
        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        # The first WA call should have come from callee_root's body
        # We assert the contact landed inside bot_callee
        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.last_chatbot_id, self.bot_callee)


# ──────────────────────────────────────────────────────────────────────────────
# Runtime: subroutine jump + return
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestSubroutineJump(JumpFixtures):

    def test_subroutine_pushes_call_stack_frame(self):
        """Subroutine mode pushes a frame with caller chatbot + return step."""
        self.caller_jump.jump_mode = 'subroutine'
        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        self.contact.invalidate_recordset()
        stack = self.contact.call_stack or []
        # If the callee ran straight through to end_flow (auto-advance), the
        # frame is already popped — that's also a valid outcome to assert.
        # So we re-run with a callee that waits for input instead.
        # (See dedicated tests below for end-to-end return semantics.)
        self.assertTrue(
            stack or self.contact.last_chatbot_id == self.bot_caller,
            "Expected either an active frame or a completed return")

    def test_subroutine_end_flow_pops_frame_and_resumes_caller(self):
        """end_flow in callee with active stack returns to caller's continuation."""
        self.caller_jump.jump_mode = 'subroutine'
        # Use a callee that waits for user input so we control when end_flow fires.
        callee_question = self.env['whatsapp.chatbot.step'].create({
            'name': 'Callee Question',
            'chatbot_id': self.bot_callee.id,
            'step_type': 'question_text',
            'body_plain': 'Say END to finish.',
            'sequence': 5,
        })
        # Rewire callee_root → callee_question → end
        self.callee_end.parent_id = callee_question.id
        self.caller_jump.target_step_id = callee_question.id

        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)

        # Frame should be on the stack now (waiting for user input on callee_question)
        self.contact.invalidate_recordset()
        self.assertEqual(len(self.contact.call_stack or []), 1)
        self.assertEqual(self.contact.last_chatbot_id, self.bot_callee)
        self.assertEqual(self.contact.last_step_id, callee_question)

        # User replies → routes to end_flow child → pops frame, resumes caller
        reply = self._make_incoming(callee_question, body='END',
                                    chatbot=self.bot_callee)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(reply)

        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.call_stack or [], [],
                         "Frame must be popped after end_flow")
        self.assertEqual(self.contact.last_chatbot_id, self.bot_caller)
        # The runtime advances from the jump step's first child after return
        # → caller_after_return is a 'message' step that auto-sends.
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.caller_after_return.id),
        ])
        self.assertTrue(outgoing, "Caller should resume at caller_after_return")

    def test_end_flow_without_stack_terminates(self):
        """end_flow in the root flow (no stack) still terminates normally."""
        msg = self._make_incoming(self.callee_root, body='done',
                                  chatbot=self.bot_callee)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._handle_end_flow(
                msg, self.callee_end)
        mock_send.assert_not_called()
        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.last_step_id, self.callee_end)


# ──────────────────────────────────────────────────────────────────────────────
# Variable mapping
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestVariableMapping(JumpFixtures):

    def test_in_mapping_copies_caller_to_callee_on_jump(self):
        """direction='in' copies caller var value → callee var on jump."""
        self.caller_jump.jump_mode = 'one_way'
        self.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': self.caller_jump.id,
            'source_variable_id': self.caller_name_var.id,
            'target_variable_id': self.callee_name_var.id,
            'direction': 'in',
        })
        self._set_value(self.contact, self.caller_name_var, 'Alice')

        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)

        self.assertEqual(self._get_value(self.contact, self.callee_name_var), 'Alice')

    def test_out_mapping_copies_callee_to_caller_on_return(self):
        """direction='out' copies callee var → caller var on subroutine return."""
        self.caller_jump.jump_mode = 'subroutine'
        self.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': self.caller_jump.id,
            'source_variable_id': self.caller_result_var.id,
            'target_variable_id': self.callee_result_var.id,
            'direction': 'out',
        })

        # Pre-seed callee's result var as if the callee filled it during its run
        self._set_value(self.contact, self.callee_result_var, 'sub-output')

        # Manually push a frame as if a jump happened (avoids tying this test
        # to the full callee run-through).
        out_rows = [{
            'src_var': self.caller_result_var.id,
            'tgt_var': self.callee_result_var.id,
        }]
        self.contact.call_stack = [{
            'caller_chatbot_id': self.bot_caller.id,
            'return_step_id': self.caller_jump.id,
            'out_mapping': out_rows,
        }]
        self.contact.last_chatbot_id = self.bot_callee.id
        self.contact.last_step_id = self.callee_end.id

        msg = self._make_incoming(self.callee_end, body='end',
                                  chatbot=self.bot_callee)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._handle_end_flow(msg, self.callee_end)

        # Caller's result var should now hold the callee's value
        self.assertEqual(self._get_value(self.contact, self.caller_result_var), 'sub-output')

    def test_both_mapping_copies_each_direction(self):
        """direction='both' copies on jump AND on return."""
        self.caller_jump.jump_mode = 'subroutine'
        self.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': self.caller_jump.id,
            'source_variable_id': self.caller_name_var.id,
            'target_variable_id': self.callee_name_var.id,
            'direction': 'both',
        })
        self._set_value(self.contact, self.caller_name_var, 'before')

        # In-jump copy
        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        self.assertEqual(self._get_value(self.contact, self.callee_name_var), 'before')

        # Mutate callee value then simulate return — should sync back
        self._set_value(self.contact, self.callee_name_var, 'after')
        # The frame is already on the stack from the jump call above (subroutine);
        # if it isn't (auto-advance popped through end_flow), re-push for test isolation.
        if not self.contact.call_stack:
            self.contact.call_stack = [{
                'caller_chatbot_id': self.bot_caller.id,
                'return_step_id': self.caller_jump.id,
                'out_mapping': [{
                    'src_var': self.caller_name_var.id,
                    'tgt_var': self.callee_name_var.id,
                }],
            }]
        end_msg = self._make_incoming(self.callee_end, body='end',
                                      chatbot=self.bot_callee)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._handle_end_flow(end_msg, self.callee_end)
        self.assertEqual(self._get_value(self.contact, self.caller_name_var), 'after')

    def test_in_mapping_skipped_for_out_direction(self):
        """direction='out' rows are NOT copied on jump (only on return)."""
        self.caller_jump.jump_mode = 'subroutine'
        self.env['whatsapp.chatbot.step.var.mapping'].create({
            'step_id': self.caller_jump.id,
            'source_variable_id': self.caller_name_var.id,
            'target_variable_id': self.callee_name_var.id,
            'direction': 'out',
        })
        self._set_value(self.contact, self.caller_name_var, 'caller_only')

        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        # Out-direction does not copy on jump → callee var should NOT receive value
        self.assertIsNone(self._get_value(self.contact, self.callee_name_var))


# ──────────────────────────────────────────────────────────────────────────────
# Nested subroutines + recursion guard
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestNestedAndGuard(JumpFixtures):

    def test_recursion_guard_refuses_jump_when_stack_full(self):
        """When call_stack already at MAX_CALL_STACK_DEPTH, further jumps are refused."""
        self.caller_jump.jump_mode = 'subroutine'
        # Saturate the call stack
        self.contact.call_stack = [
            {'caller_chatbot_id': self.bot_caller.id,
             'return_step_id': self.caller_jump.id,
             'out_mapping': []}
            for _ in range(8)
        ]
        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)
        mock_send.assert_not_called()
        self.contact.invalidate_recordset()
        self.assertEqual(len(self.contact.call_stack or []), 8,
                         "Stack must not grow past MAX_CALL_STACK_DEPTH")

    def test_nested_subroutine_pops_correctly(self):
        """A → B → C; C ends → resumes B; B ends → resumes A."""
        Step = self.env['whatsapp.chatbot.step']
        Chatbot = self.env['whatsapp.chatbot']

        bot_c = Chatbot.create({'name': 'Bot C', 'status': 'published'})
        c_root = Step.create({
            'name': 'C Root',
            'chatbot_id': bot_c.id,
            'step_type': 'question_text',
            'body_plain': 'Say end',
            'sequence': 1,
        })
        c_end = Step.create({
            'name': 'C End',
            'chatbot_id': bot_c.id,
            'step_type': 'end_flow',
            'parent_id': c_root.id,
        })

        # Wire B (= bot_callee) to jump into C as a subroutine.
        b_jump_to_c = Step.create({
            'name': 'B Jump To C',
            'chatbot_id': self.bot_callee.id,
            'step_type': 'jump_to_flow',
            'target_chatbot_id': bot_c.id,
            'jump_mode': 'subroutine',
            'parent_id': self.callee_root.id,
        })
        # Move callee_end so it lives after b_jump_to_c (return path)
        self.callee_end.parent_id = b_jump_to_c.id

        # A (= caller) keeps subroutine mode into B
        self.caller_jump.jump_mode = 'subroutine'

        msg = self._make_incoming(self.caller_jump)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)

        self.contact.invalidate_recordset()
        # Two frames on the stack: outer A→B and inner B→C
        self.assertEqual(len(self.contact.call_stack or []), 2,
                         "Two nested subroutines should push two frames")
        self.assertEqual(self.contact.last_chatbot_id, bot_c)

        # End C → pop one frame, back in B, B's only continuation is callee_end
        # which immediately ends → pop again, back in A's continuation
        reply = self._make_incoming(c_root, body='end', chatbot=bot_c)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(reply)

        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.call_stack or [], [],
                         "Both frames should be popped")
        self.assertEqual(self.contact.last_chatbot_id, self.bot_caller,
                         "Should have resumed all the way back to the caller")


# ──────────────────────────────────────────────────────────────────────────────
# Step-type matrix smoke: jump_to_flow shouldn't try to send a body
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'jump_to_flow', 'post_install', '-at_install')
class TestJumpDispatchSmoke(JumpFixtures):

    def test_jump_step_does_not_send_its_own_body(self):
        """jump_to_flow is a control-flow step; its own body is never sent."""
        # caller_jump has no body_plain — but even with one, it should not be sent
        self.caller_jump.body_plain = 'this should never be sent'
        self.caller_jump.jump_mode = 'one_way'

        msg = self._make_incoming(self.caller_jump)
        sent_bodies = []
        def capture_send(self_obj, recipient_phone=None, message_text=None, **kw):
            sent_bodies.append(message_text)
            return {'success': True, 'message_id': 'wamid.x'}

        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          autospec=True, side_effect=capture_send):
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(
                msg, self.caller_jump)

        self.assertNotIn('this should never be sent', sent_bodies,
                         "Jump step's own body must not be sent as a WhatsApp message")
