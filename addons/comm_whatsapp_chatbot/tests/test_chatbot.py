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

        # Trigger answers: "A" → opt_a, "B" → opt_b
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
        """Non-interactive step calls send_whatsapp_message."""
        msg = self._make_incoming(self.step_root, body='hi')
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            self.env['whatsapp.chatbot.message']._send_step_message(msg, self.step_root)
        mock_send.assert_called_once()

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
            'name': 'Flow Step 2',
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
