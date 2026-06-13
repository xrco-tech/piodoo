# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import common, tagged


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _mock_send_ok(*_args, **_kwargs):
    return {'success': True, 'message_id': 'wamid.test123'}


def _mock_send_fail(*_args, **_kwargs):
    return {'success': False, 'error': 'API error'}


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures mixin — creates a minimal chatbot flow shared by integration tests
# ──────────────────────────────────────────────────────────────────────────────

class ChatbotFixtures(common.TransactionCase):
    """
    DB fixtures for chatbot integration tests.

    Flow layout created in setUp:

        step_root  (message)
            └── step_question  (question_text)
                    ├── step_opt_a  (message)  – trigger: "A"
                    │       └── step_end  (end_flow)
                    └── step_opt_b  (message)  – trigger: "B"
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.chatbot = cls.env['whatsapp.chatbot'].create({
            'name': 'Test Bot',
            'status': 'published',
        })

        cls.step_root = cls.env['whatsapp.chatbot.step'].create({
            'name': 'Welcome',
            'chatbot_id': cls.chatbot.id,
            'step_type': 'message',
            'body_plain': 'Welcome! Type A or B.',
            'sequence': 1,
        })

        cls.step_question = cls.env['whatsapp.chatbot.step'].create({
            'name': 'Choose option',
            'chatbot_id': cls.chatbot.id,
            'step_type': 'question_text',
            'body_plain': 'Please choose A or B.',
            'parent_id': cls.step_root.id,
            'sequence': 10,
        })

        cls.step_opt_a = cls.env['whatsapp.chatbot.step'].create({
            'name': 'Option A',
            'chatbot_id': cls.chatbot.id,
            'step_type': 'message',
            'body_plain': 'You chose A.',
            'parent_id': cls.step_question.id,
            'sequence': 10,
        })

        cls.step_end = cls.env['whatsapp.chatbot.step'].create({
            'name': 'End',
            'chatbot_id': cls.chatbot.id,
            'step_type': 'end_flow',
            'body_plain': '',
            'parent_id': cls.step_opt_a.id,
            'sequence': 10,
        })

        cls.step_opt_b = cls.env['whatsapp.chatbot.step'].create({
            'name': 'Option B',
            'chatbot_id': cls.chatbot.id,
            'step_type': 'message',
            'body_plain': 'You chose B.',
            'parent_id': cls.step_question.id,
            'sequence': 20,
        })

        # Trigger answers: "A" → opt_a, "B" → opt_b.
        # trigger_answer_ids is Many2many — must be set explicitly on the child step.
        cls.answer_a = cls.env['whatsapp.chatbot.answer'].create({
            'value': 'A',
            'step_id': cls.step_opt_a.id,
            'operator': 'is_equal_to',
        })
        cls.answer_b = cls.env['whatsapp.chatbot.answer'].create({
            'value': 'B',
            'step_id': cls.step_opt_b.id,
            'operator': 'is_equal_to',
        })
        cls.step_opt_a.write({'trigger_answer_ids': [(4, cls.answer_a.id)]})
        cls.step_opt_b.write({'trigger_answer_ids': [(4, cls.answer_b.id)]})

        cls.partner = cls.env['res.partner'].create({
            'name': 'Test User',
            'mobile': '27600000001',
        })
        cls.contact = cls.env['whatsapp.chatbot.contact'].create({
            'partner_id': cls.partner.id,
        })

    def _make_incoming(self, step, body='hello'):
        """Create an incoming chatbot message at the given step."""
        return self.env['whatsapp.chatbot.message'].create({
            'contact_id': self.contact.id,
            'chatbot_id': self.chatbot.id,
            'step_id': step.id,
            'mobile_number': '27600000001',
            'message_plain': body,
            'type': 'incoming',
        })


# ──────────────────────────────────────────────────────────────────────────────
# 1. Pure-logic: _evaluate_answer_condition
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestEvaluateAnswerCondition(common.TransactionCase):

    def _answer(self, operator, value, data_type='text'):
        a = MagicMock()
        a.operator = operator
        a.value = value
        a.answer_data_type = data_type
        return a

    def _model(self):
        return self.env['whatsapp.chatbot.message']

    # guard conditions
    def test_no_answer_record_returns_false(self):
        self.assertFalse(self._model()._evaluate_answer_condition(None, 'hello'))

    def test_empty_user_answer_returns_false(self):
        a = self._answer('is_equal_to', 'hello')
        self.assertFalse(self._model()._evaluate_answer_condition(a, ''))
        self.assertFalse(self._model()._evaluate_answer_condition(a, None))

    # is_equal_to (case-insensitive for text)
    def test_is_equal_to_match(self):
        a = self._answer('is_equal_to', 'yes')
        self.assertTrue(self._model()._evaluate_answer_condition(a, 'YES'))
        self.assertTrue(self._model()._evaluate_answer_condition(a, 'yes'))

    def test_is_equal_to_no_match(self):
        a = self._answer('is_equal_to', 'yes')
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'no'))

    # is_not_equal_to
    def test_is_not_equal_to(self):
        a = self._answer('is_not_equal_to', 'yes')
        self.assertTrue(self._model()._evaluate_answer_condition(a, 'no'))
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'YES'))

    # contains
    def test_contains_match(self):
        a = self._answer('contains', 'BOOK')
        self.assertTrue(self._model()._evaluate_answer_condition(a, 'I WANT TO BOOK'))

    def test_contains_no_match(self):
        a = self._answer('contains', 'BOOK')
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'I WANT TO CANCEL'))

    # does_not_contain
    def test_does_not_contain(self):
        a = self._answer('does_not_contain', 'CANCEL')
        self.assertTrue(self._model()._evaluate_answer_condition(a, 'I WANT TO BOOK'))
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'CANCEL THIS'))

    # numeric operators
    def test_less_than_numeric(self):
        a = self._answer('less_than', '10', data_type='number')
        self.assertTrue(self._model()._evaluate_answer_condition(a, '5'))
        self.assertFalse(self._model()._evaluate_answer_condition(a, '15'))

    def test_greater_than_numeric(self):
        a = self._answer('greater_than', '5', data_type='number')
        self.assertTrue(self._model()._evaluate_answer_condition(a, '10'))
        self.assertFalse(self._model()._evaluate_answer_condition(a, '3'))

    def test_numeric_with_invalid_input_returns_false(self):
        a = self._answer('less_than', '10', data_type='number')
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'not_a_number'))

    def test_unknown_operator_returns_false(self):
        a = self._answer('some_future_op', 'x')
        self.assertFalse(self._model()._evaluate_answer_condition(a, 'x'))


# ──────────────────────────────────────────────────────────────────────────────
# 2. Pure-logic: _replace_variables_in_message
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestReplaceVariables(common.TransactionCase):

    def _model(self):
        return self.env['whatsapp.chatbot.message']

    def test_replaces_known_variable(self):
        result = self._model()._replace_variables_in_message(
            'Hello {{variables.name}}!', {'name': 'Alice'})
        self.assertEqual(result, 'Hello Alice!')

    def test_preserves_unknown_variable(self):
        result = self._model()._replace_variables_in_message(
            'Hello {{variables.name}}!', {})
        self.assertEqual(result, 'Hello {{variables.name}}!')

    def test_replaces_record_with_value_attr(self):
        mock_var = MagicMock()
        mock_var.value = 'Bob'
        result = self._model()._replace_variables_in_message(
            'Hi {{variables.user}}', {'user': mock_var})
        self.assertEqual(result, 'Hi Bob')

    def test_multiple_variables(self):
        result = self._model()._replace_variables_in_message(
            '{{variables.greeting}} {{variables.name}}',
            {'greeting': 'Hey', 'name': 'Charlie'})
        self.assertEqual(result, 'Hey Charlie')

    def test_empty_message_returns_empty(self):
        self.assertEqual(self._model()._replace_variables_in_message('', {}), '')
        self.assertEqual(self._model()._replace_variables_in_message(None, {}), '')


# ──────────────────────────────────────────────────────────────────────────────
# 3. _find_matching_child_step — keyword routing
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestFindMatchingChildStep(ChatbotFixtures):

    def test_returns_none_when_no_answer(self):
        step, answer = self.env['whatsapp.chatbot.message']._find_matching_child_step(
            self.step_question, '')
        self.assertFalse(step)

    def test_matches_keyword_a(self):
        step, answer = self.env['whatsapp.chatbot.message']._find_matching_child_step(
            self.step_question, 'A')
        self.assertEqual(step, self.step_opt_a)

    def test_matches_keyword_b(self):
        step, answer = self.env['whatsapp.chatbot.message']._find_matching_child_step(
            self.step_question, 'b')  # case-insensitive
        self.assertEqual(step, self.step_opt_b)

    def test_no_match_returns_none(self):
        step, answer = self.env['whatsapp.chatbot.message']._find_matching_child_step(
            self.step_question, 'UNKNOWN')
        self.assertFalse(step)

    def test_step_without_children_returns_none(self):
        step, answer = self.env['whatsapp.chatbot.message']._find_matching_child_step(
            self.step_end, 'anything')
        self.assertFalse(step)


# ──────────────────────────────────────────────────────────────────────────────
# 4. _process_chatbot_flow — routing + auto-advance
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestProcessChatbotFlow(ChatbotFixtures):

    def test_fallback_to_first_child_when_no_match(self):
        """Unrecognised answer falls back to first child (step_opt_a by sequence/id)."""
        msg = self._make_incoming(self.step_question, body='something_random')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            result = self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg)
        # An outgoing message should have been created for step_opt_a
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.step_opt_a.id),
        ], limit=1)
        self.assertTrue(outgoing, "Expected outgoing message for fallback step (opt_a)")

    def test_routes_to_matched_step(self):
        """Answer 'B' routes to step_opt_b."""
        msg = self._make_incoming(self.step_question, body='B')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg)
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.step_opt_b.id),
        ], limit=1)
        self.assertTrue(outgoing, "Expected outgoing message for step_opt_b")

    def test_stops_at_end_flow(self):
        """When the matched next step is end_flow, no outgoing message is sent."""
        msg = self._make_incoming(self.step_opt_a, body='anything')
        before = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg)
        after = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        self.assertEqual(before, after, "No new outgoing message should be created at end_flow")

    def test_max_recursion_depth_guard(self):
        """Recursion guard returns safely without crashing."""
        msg = self._make_incoming(self.step_question, body='A')
        result = self.env['whatsapp.chatbot.message']._process_chatbot_flow(
            msg, depth=11)
        self.assertEqual(result, msg)


# ──────────────────────────────────────────────────────────────────────────────
# 5. _handle_incoming_message — trigger vs. reply dispatch
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestHandleIncomingMessage(ChatbotFixtures):

    def test_trigger_sends_first_step(self):
        """from_trigger=True: bot sends the step's own message."""
        msg = self._make_incoming(self.step_root, body='HI')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._handle_incoming_message(
                msg, from_trigger=True)
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.step_root.id),
        ], limit=1)
        self.assertTrue(outgoing, "Bot should send step_root message on trigger")

    def test_reply_processes_flow(self):
        """from_trigger=False: treats body as answer and advances."""
        msg = self._make_incoming(self.step_question, body='A')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._handle_incoming_message(
                msg, from_trigger=False)
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.step_opt_a.id),
        ], limit=1)
        self.assertTrue(outgoing, "Reply 'A' should route to step_opt_a")

    def test_no_chatbot_id_returns_early(self):
        """Message without chatbot_id must not crash."""
        msg = self._make_incoming(self.step_root, body='HI')
        msg.chatbot_id = False
        msg.step_id = False
        result = self.env['whatsapp.chatbot.message']._handle_incoming_message(msg)
        self.assertEqual(result, msg)

    def test_no_step_finds_first_step(self):
        """No step_id → bot sends the root step."""
        msg = self._make_incoming(self.step_root, body='HELLO')
        msg.step_id = False
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._handle_incoming_message(
                msg, from_trigger=True)
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', self.step_root.id),
        ], limit=1)
        self.assertTrue(outgoing)


# ──────────────────────────────────────────────────────────────────────────────
# 6. _send_step_message — WA API dispatch and auto-advance
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestSendStepMessage(ChatbotFixtures):

    def test_empty_body_returns_without_sending(self):
        """Step with no body_plain must not call the WA API."""
        empty_step = self.env['whatsapp.chatbot.step'].create({
            'name': 'Empty',
            'chatbot_id': self.chatbot.id,
            'step_type': 'message',
            'body_plain': '',
        })
        msg = self._make_incoming(empty_step, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            result = self.env['whatsapp.chatbot.message']._send_step_message(msg, empty_step)
        mock_send.assert_not_called()
        self.assertEqual(result, msg)

    def test_regular_step_calls_send_whatsapp_message(self):
        """Non-interactive step calls send_whatsapp_message (may auto-advance too)."""
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, self.step_root)
        mock_send.assert_called()  # called at least once (may auto-advance)

    def test_api_failure_logs_error_and_returns(self):
        """If WA API returns failure, no outgoing chatbot message is created."""
        msg = self._make_incoming(self.step_root, body='hi')
        before = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_fail):
            self.env['whatsapp.chatbot.message']._send_step_message(msg, self.step_root)
        after = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        self.assertEqual(before, after)

    def test_question_text_does_not_auto_advance(self):
        """question_text step waits for user input — must NOT auto-advance."""
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._send_step_message(
                msg, self.step_question)
        outgoing_count = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        # Exactly one outgoing (the question itself), never the child step
        self.assertEqual(outgoing_count, 1)
        only_outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        self.assertEqual(only_outgoing.step_id, self.step_question)

    def test_message_step_auto_advances_to_single_child(self):
        """A 'message' step with one non-end child auto-advances after sending."""
        # step_opt_b has no children → no auto-advance possible; use step_root which
        # has step_question as its single child
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._send_step_message(msg, self.step_root)
        # After sending step_root (message), it should auto-advance to step_question
        outgoing_steps = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing'),
        ]).mapped('step_id')
        self.assertIn(self.step_root, outgoing_steps)
        self.assertIn(self.step_question, outgoing_steps,
                      "Should auto-advance from step_root to step_question")

    def test_interactive_flow_step_calls_send_interactive_flow(self):
        """question_interactive + interactive_flow → calls send_whatsapp_interactive_flow."""
        step_flow = self.env['whatsapp.chatbot.step'].create({
            'name': 'Flow Step',
            'chatbot_id': self.chatbot.id,
            'step_type': 'question_interactive',
            'wa_message_type': 'interactive_flow',
            'body_plain': 'Fill in this form.',
            'flow_action': 'navigate',
            'flow_cta': 'Start',
        })
        # Attach a dummy flow record so flow_uid is non-empty
        flow = self.env['whatsapp.flow'].search([], limit=1)
        if flow:
            step_flow.flow_id = flow.id

        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_interactive_flow',
                          side_effect=_mock_send_ok) as mock_flow_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, step_flow)
        mock_flow_send.assert_called_once()

    def test_interactive_flow_step_does_not_auto_advance(self):
        """question_interactive step must not auto-advance (waits for flow completion)."""
        step_flow = self.env['whatsapp.chatbot.step'].create({
            'name': 'Flow Step Two',
            'chatbot_id': self.chatbot.id,
            'step_type': 'question_interactive',
            'wa_message_type': 'interactive_flow',
            'body_plain': 'Fill in this form.',
            'flow_action': 'navigate',
            'flow_cta': 'Start',
            'parent_id': self.step_root.id,
        })
        # Give it a child so auto-advance would be attempted if bug present
        self.env['whatsapp.chatbot.step'].create({
            'name': 'Post-flow step',
            'chatbot_id': self.chatbot.id,
            'step_type': 'message',
            'body_plain': 'Thanks.',
            'parent_id': step_flow.id,
        })
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_interactive_flow',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._send_step_message(msg, step_flow)
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing'),
        ])
        self.assertEqual(len(outgoing), 1,
                         "Only the flow step itself should be sent, not the child")
        self.assertEqual(outgoing.step_id, step_flow)


# ──────────────────────────────────────────────────────────────────────────────
# 7. All step types — dispatch and auto-advance behaviour
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestStepTypes(ChatbotFixtures):
    """Covers every step_type and wa_message_type to verify WA dispatch and auto-advance rules."""

    def _step(self, name, step_type, body='Test message.', **kw):
        vals = {'name': name, 'chatbot_id': self.chatbot.id,
                'step_type': step_type, 'body_plain': body}
        vals.update(kw)
        return self.env['whatsapp.chatbot.step'].create(vals)

    # ── Input question types (NOT in WAIT_FOR_INPUT) → auto-advance ───────────

    def test_input_question_types_auto_advance(self):
        """question_numeric/phone/email/date are NOT in WAIT_FOR_INPUT → auto-advance to single child."""
        cases = [
            ('question_numeric', 'Numeric Question'),
            ('question_phone', 'Phone Question'),
            ('question_email', 'Email Question'),
            ('question_date', 'Date Question'),
        ]
        for step_type, name in cases:
            parent = self._step(name, step_type, body='Please provide input.')
            self._step('Auto Child', 'message', body='Thanks.', parent_id=parent.id)
            msg = self._make_incoming(parent, body='hi')
            with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                              side_effect=_mock_send_ok) as mock_send:
                self.env['whatsapp.chatbot.message']._send_step_message(msg, parent)
            self.assertGreaterEqual(
                mock_send.call_count, 2,
                f"{step_type}: expected auto-advance (>=2 sends), got {mock_send.call_count}")

    def test_media_question_types_auto_advance(self):
        """question_document/image/video/audio are NOT in WAIT_FOR_INPUT → auto-advance to single child."""
        cases = [
            ('question_document', 'Document Question'),
            ('question_image', 'Image Question'),
            ('question_video', 'Video Question'),
            ('question_audio', 'Audio Question'),
        ]
        for step_type, name in cases:
            parent = self._step(name, step_type, body='Please send the file.')
            self._step('Media Child', 'message', body='Received.', parent_id=parent.id)
            msg = self._make_incoming(parent, body='hi')
            with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                              side_effect=_mock_send_ok) as mock_send:
                self.env['whatsapp.chatbot.message']._send_step_message(msg, parent)
            self.assertGreaterEqual(
                mock_send.call_count, 2,
                f"{step_type}: expected auto-advance (>=2 sends), got {mock_send.call_count}")

    # ── set_variable / execute_code → no WA API call ──────────────────────────

    def test_set_variable_does_not_call_wa_api(self):
        """set_variable is processed silently — no WA message sent."""
        step = self._step('Set Variable', 'set_variable', body='Setting variable.')
        msg = self._make_incoming(step, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._handle_incoming_message(
                msg, from_trigger=True)
        mock_send.assert_not_called()

    def test_execute_code_does_not_call_wa_api(self):
        """execute_code is processed silently — no WA message sent."""
        step = self._step('Execute Code', 'execute_code', body='Running code.')
        msg = self._make_incoming(step, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._handle_incoming_message(
                msg, from_trigger=True)
        mock_send.assert_not_called()

    def test_set_variable_in_flow_advances_to_next(self):
        """set_variable mid-flow: _process_chatbot_flow routes through it and advances."""
        step_var = self._step('Capture Name', 'set_variable', body='')
        step_reply = self._step('Name Saved', 'message', body='Name saved!', parent_id=step_var.id)
        # Trigger _process_chatbot_flow from step_var's parent — set_variable is the next step
        msg = self._make_incoming(step_var, body='Alice')
        # _process_chatbot_flow on step_var: no children to route to → returns early
        # Instead, test via _handle_incoming_message with from_trigger=False on a parent
        parent = self._step('Ask Name', 'question_text', body='What is your name?')
        step_var.parent_id = parent.id
        msg2 = self._make_incoming(parent, body='Alice')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            result = self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg2)
        # set_variable step was selected (only child) and processed via _process_variable_or_code_step
        self.assertEqual(result, msg2)

    # ── jump_to_flow → no WA call (control-flow only) ─────────────────────────

    def test_jump_to_flow_does_not_call_wa_api(self):
        """jump_to_flow is control-flow only — never sends its own body."""
        other_bot = self.env['whatsapp.chatbot'].create({
            'name': 'Other Bot', 'status': 'published',
        })
        other_root = self.env['whatsapp.chatbot.step'].create({
            'name': 'Other Root',
            'chatbot_id': other_bot.id,
            'step_type': 'message',
            'body_plain': 'From other bot.',
            'sequence': 1,
        })
        jump = self._step(
            'Bridge Jump', 'jump_to_flow',
            body='ignored body',
            target_chatbot_id=other_bot.id,
            target_step_id=other_root.id,
            jump_mode='one_way',
        )
        msg = self._make_incoming(jump, body='go')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._process_jump_to_flow_step(msg, jump)
        # The callee root message gets sent — but the jump step's own 'ignored body' never.
        sent_bodies = [c.kwargs.get('message_text') for c in mock_send.call_args_list]
        self.assertNotIn('ignored body', sent_bodies)

    # ── transfer_to_agent → sends its body via send_whatsapp_message ──────────

    def test_transfer_to_agent_sends_message(self):
        """transfer_to_agent has no special routing — sends its body normally."""
        step = self._step('Transfer Agent', 'transfer_to_agent',
                          body='Connecting you to an agent.')
        msg = self._make_incoming(step, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, step)
        mock_send.assert_called_once()

    # ── end_flow → terminates the flow and updates contact state ─────────────

    def test_end_flow_does_not_send_message(self):
        """_process_chatbot_flow stops at end_flow without calling WA API."""
        # step_opt_a's only child is step_end (end_flow)
        msg = self._make_incoming(self.step_opt_a, body='done')
        before = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg)
        after = self.env['whatsapp.chatbot.message'].search_count([
            ('contact_id', '=', self.contact.id), ('type', '=', 'outgoing')])
        mock_send.assert_not_called()
        self.assertEqual(before, after, "end_flow must not create any outgoing message")

    def test_end_flow_updates_contact_last_step(self):
        """After reaching end_flow, contact.last_step_id is set to the end_flow step."""
        msg = self._make_incoming(self.step_opt_a, body='done')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_chatbot_flow(msg)
        self.contact.invalidate_recordset()
        self.assertEqual(self.contact.last_step_id, self.step_end,
                         "Contact's last_step_id must be updated to the end_flow step")

    # ── interactive_button / interactive_list → send_whatsapp_message ─────────

    def test_interactive_button_uses_send_whatsapp_message(self):
        """question_interactive + interactive_button → send_whatsapp_message, not interactive_flow."""
        step = self._step('Button Question', 'question_interactive',
                          body='Choose an option.',
                          wa_message_type='interactive_button')
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send, \
             patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_interactive_flow',
                          side_effect=_mock_send_ok) as mock_flow:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, step)
        mock_send.assert_called_once()
        mock_flow.assert_not_called()

    def test_interactive_list_uses_send_whatsapp_message(self):
        """question_interactive + interactive_list → send_whatsapp_message, not interactive_flow."""
        step = self._step('List Question', 'question_interactive',
                          body='Pick from the list.',
                          wa_message_type='interactive_list')
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send, \
             patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_interactive_flow',
                          side_effect=_mock_send_ok) as mock_flow:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, step)
        mock_send.assert_called_once()
        mock_flow.assert_not_called()

    # ── message with multiple / no children → no auto-advance ─────────────────

    def test_message_with_multiple_children_no_auto_advance(self):
        """message step with >1 children sends once (auto-advance requires exactly 1 child)."""
        parent = self._step('Branching Step', 'message', body='Which path?')
        self._step('Branch One', 'message', body='Path one.', parent_id=parent.id, sequence=1)
        self._step('Branch Two', 'message', body='Path two.', parent_id=parent.id, sequence=2)
        msg = self._make_incoming(parent, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, parent)
        mock_send.assert_called_once()

    def test_message_with_no_children_no_auto_advance(self):
        """message step with no children sends once then stops."""
        leaf = self._step('Leaf Step', 'message', body='This is the end.')
        msg = self._make_incoming(leaf, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, leaf)
        mock_send.assert_called_once()

    def test_message_with_end_flow_child_no_auto_advance(self):
        """message step whose only child is end_flow must NOT auto-advance."""
        parent = self._step('Closing Message', 'message', body='Goodbye!')
        self._step('Flow End', 'end_flow', body='', parent_id=parent.id)
        msg = self._make_incoming(parent, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, parent)
        mock_send.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 8. _resolve_trigger_for_engaged — cross-bot trigger switching
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestResolveTriggerForEngaged(ChatbotFixtures):
    """An engaged contact who sends a trigger word should:
       — restart the current bot if the trigger belongs to it (existing)
       — switch to another bot if the trigger belongs there (new behavior)
       — fall through (no match) for free-text replies"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Second bot with its own root step + trigger word
        cls.other_bot = cls.env['whatsapp.chatbot'].create({
            'name': 'Other Bot', 'status': 'published',
        })
        cls.env['whatsapp.chatbot.step'].create({
            'name': 'Other Root',
            'chatbot_id': cls.other_bot.id,
            'step_type': 'message',
            'body_plain': 'Hi from other bot.',
            'sequence': 1,
        })
        cls.env['whatsapp.chatbot.trigger'].create({
            'name': 'JUMPDEMO', 'chatbot_id': cls.other_bot.id,
        })
        # Existing fixture bot keeps its own trigger
        cls.env['whatsapp.chatbot.trigger'].create({
            'name': 'RESTART', 'chatbot_id': cls.chatbot.id,
        })

    def test_same_bot_trigger_returns_restart(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, 'RESTART')
        self.assertEqual(target, self.chatbot)
        self.assertEqual(kind, 'restart')

    def test_same_bot_trigger_is_case_insensitive(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, 'restart')
        self.assertEqual(target, self.chatbot)
        self.assertEqual(kind, 'restart')

    def test_trigger_matches_mixed_case_stored_name(self):
        """Trigger stored as 'Demo' (mixed case) must match user typing
        'demo', 'DEMO', or 'Demo' — regression for case-sensitive lookup."""
        mixed = self.env['whatsapp.chatbot'].create({
            'name': 'Mixed Case Bot', 'status': 'published',
        })
        self.env['whatsapp.chatbot.trigger'].create({
            'name': 'Demo', 'chatbot_id': mixed.id,
        })
        for typed in ('demo', 'DEMO', 'Demo', 'dEmO'):
            target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
                self.chatbot, typed)
            self.assertEqual(target, mixed,
                             f"'{typed}' must match stored trigger 'Demo'")
            self.assertEqual(kind, 'switch')

    def test_cross_bot_trigger_returns_switch(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, 'JUMPDEMO')
        self.assertEqual(target, self.other_bot)
        self.assertEqual(kind, 'switch')

    def test_no_match_returns_none(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, 'just some reply text')
        self.assertFalse(target)
        self.assertIsNone(kind)

    def test_empty_message_returns_none(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, '')
        self.assertFalse(target)
        self.assertIsNone(kind)

    def test_same_bot_wins_when_trigger_exists_on_both(self):
        """If the same name is a trigger on both the current bot AND another bot,
        the same-bot trigger wins (restart, not switch)."""
        # Add 'RESTART' to other_bot too
        self.env['whatsapp.chatbot.trigger'].create({
            'name': 'RESTART', 'chatbot_id': self.other_bot.id,
        })
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.chatbot, 'RESTART')
        self.assertEqual(target, self.chatbot)
        self.assertEqual(kind, 'restart')

    def test_no_current_bot_returns_none(self):
        target, kind = self.env['whatsapp.chatbot.message']._resolve_trigger_for_engaged(
            self.env['whatsapp.chatbot'], 'JUMPDEMO')
        self.assertFalse(target)
        self.assertIsNone(kind)


# ──────────────────────────────────────────────────────────────────────────────
# 9. _process_variable_or_code_step — actually save and auto-advance
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'post_install', '-at_install')
class TestVariableOrCodeStep(ChatbotFixtures):
    """set_variable must persist a value and continue down the tree.
    Pre-existing skeleton did neither — this is the regression that broke jumps."""

    def _get_value(self, contact, variable):
        rec = self.env['whatsapp.chatbot.value'].search([
            ('contact_id', '=', contact.id),
            ('variable_id', '=', variable.id),
        ], limit=1)
        return rec.value if rec else None

    def test_set_variable_static_saves_value(self):
        var = self.env['whatsapp.chatbot.variable'].create({
            'name': 'pet', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        step = self.env['whatsapp.chatbot.step'].create({
            'name': 'Save Pet',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': var.id,
            'variable_data_source': 'static',
            'variable_value': 'dog',
        })
        msg = self._make_incoming(step, body='whatever')
        self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, step)
        self.assertEqual(self._get_value(self.contact, var), 'dog')

    def test_set_variable_answer_saves_user_reply(self):
        """source='answer' takes the latest incoming message for source_step_id."""
        var = self.env['whatsapp.chatbot.variable'].create({
            'name': 'username', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        # Reuse step_question (question_text) as the source
        save = self.env['whatsapp.chatbot.step'].create({
            'name': 'Save Username',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': var.id,
            'variable_data_source': 'answer',
            'source_step_id': self.step_question.id,
            'parent_id': self.step_question.id,
        })
        # User answers the question
        msg = self._make_incoming(self.step_question, body='Alice')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok):
            self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, save)
        self.assertEqual(self._get_value(self.contact, var), 'Alice')

    def test_set_variable_from_other_variable_copies_value(self):
        src = self.env['whatsapp.chatbot.variable'].create({
            'name': 'src_var', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        tgt = self.env['whatsapp.chatbot.variable'].create({
            'name': 'tgt_var', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        self.env['whatsapp.chatbot.value'].create({
            'contact_id': self.contact.id, 'variable_id': src.id, 'value': 'copied',
        })
        step = self.env['whatsapp.chatbot.step'].create({
            'name': 'Copy Var',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': tgt.id,
            'variable_data_source': 'variable',
            'source_variable_id': src.id,
        })
        msg = self._make_incoming(step, body='go')
        self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, step)
        self.assertEqual(self._get_value(self.contact, tgt), 'copied')

    def test_set_variable_upserts_existing_value(self):
        """Re-setting the same variable updates the value, not creates duplicates."""
        var = self.env['whatsapp.chatbot.variable'].create({
            'name': 'mood', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        step = self.env['whatsapp.chatbot.step'].create({
            'name': 'Set Mood',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': var.id,
            'variable_data_source': 'static',
            'variable_value': 'happy',
        })
        msg = self._make_incoming(step)
        self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, step)
        # Now overwrite
        step.variable_value = 'sad'
        msg2 = self._make_incoming(step)
        self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg2, step)
        self.assertEqual(self._get_value(self.contact, var), 'sad')
        count = self.env['whatsapp.chatbot.value'].search_count([
            ('contact_id', '=', self.contact.id),
            ('variable_id', '=', var.id),
        ])
        self.assertEqual(count, 1, "set_variable must upsert, not duplicate")

    def test_set_variable_auto_advances_to_message_child(self):
        """After saving the variable, runtime advances to the single message child."""
        var = self.env['whatsapp.chatbot.variable'].create({
            'name': 'topic', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        save = self.env['whatsapp.chatbot.step'].create({
            'name': 'Save Topic',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': var.id,
            'variable_data_source': 'static',
            'variable_value': 'weather',
        })
        ack = self.env['whatsapp.chatbot.step'].create({
            'name': 'Ack',
            'chatbot_id': self.chatbot.id,
            'step_type': 'message',
            'body_plain': 'Saved topic.',
            'parent_id': save.id,
        })
        msg = self._make_incoming(save)
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, save)
        mock_send.assert_called()
        outgoing = self.env['whatsapp.chatbot.message'].search([
            ('contact_id', '=', self.contact.id),
            ('type', '=', 'outgoing'),
            ('step_id', '=', ack.id),
        ])
        self.assertTrue(outgoing, "Should have auto-advanced and sent Ack")

    def test_set_variable_chain_executes_through_jump(self):
        """set_variable → jump_to_flow chain: the jump is reached and dispatched."""
        target_bot = self.env['whatsapp.chatbot'].create({
            'name': 'Sub Bot', 'status': 'published',
        })
        target_root = self.env['whatsapp.chatbot.step'].create({
            'name': 'Sub Root',
            'chatbot_id': target_bot.id,
            'step_type': 'message',
            'body_plain': 'Sub body.',
        })
        var = self.env['whatsapp.chatbot.variable'].create({
            'name': 'transient', 'data_type': 'text', 'chatbot_id': self.chatbot.id,
        })
        save = self.env['whatsapp.chatbot.step'].create({
            'name': 'Pre Jump Save',
            'chatbot_id': self.chatbot.id,
            'step_type': 'set_variable',
            'variable_id': var.id,
            'variable_data_source': 'static',
            'variable_value': 'x',
        })
        self.env['whatsapp.chatbot.step'].create({
            'name': 'Jump After Save',
            'chatbot_id': self.chatbot.id,
            'step_type': 'jump_to_flow',
            'target_chatbot_id': target_bot.id,
            'target_step_id': target_root.id,
            'jump_mode': 'one_way',
            'parent_id': save.id,
        })
        msg = self._make_incoming(save)
        sent = []
        def capture(self_obj, recipient_phone=None, message_text=None, **kw):
            sent.append(message_text)
            return {'success': True, 'message_id': 'wamid.chain'}
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          autospec=True, side_effect=capture):
            self.env['whatsapp.chatbot.message']._process_variable_or_code_step(msg, save)
        # Variable was saved AND the jump reached the target bot's body
        self.assertEqual(self._get_value(self.contact, var), 'x')
        self.assertIn('Sub body.', sent)
