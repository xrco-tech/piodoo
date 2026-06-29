# -*- coding: utf-8 -*-
"""Tests for the Agent Workspace backend: voice outbound is captured
not sent; the call-session lifecycle persists session_state on the record."""

from unittest.mock import patch

from odoo.tests import common, tagged


def _mock_send_ok(*_args, **_kwargs):
    return {'success': True, 'message_id': 'wamid.fake', 'error': None}


class WorkspaceFixtures(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Step = cls.env['whatsapp.chatbot.step']
        cls.bot = cls.env['whatsapp.chatbot'].create({
            'name': 'Voice Test Script',
            'channel': 'voice',
            'status': 'published',
        })
        cls.env['whatsapp.chatbot.trigger'].create({
            'name': 'GO', 'chatbot_id': cls.bot.id,
        })
        cls.greet = Step.create({
            'name': 'Greeting', 'chatbot_id': cls.bot.id,
            'step_type': 'message', 'body_plain': 'Hello there.',
            'coaching_notes': 'Warm tone.',
            'crm_action': '[Open contact card.]',
        })
        cls.ask = Step.create({
            'name': 'Ask Name', 'chatbot_id': cls.bot.id,
            'step_type': 'question_text', 'body_plain': "What's your name?",
            'parent_id': cls.greet.id, 'sequence': 10,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Caller', 'mobile': '+27600000801',
        })
        cls.contact = cls.env['whatsapp.chatbot.contact'].create({
            'partner_id': cls.partner.id,
        })


# ──────────────────────────────────────────────────────────────────────────────
# Voice outbound: no real send + capture works
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'voice', 'workspace', 'post_install', '-at_install')
class TestVoiceOutboundNoOp(WorkspaceFixtures):

    def test_voice_send_does_not_call_whatsapp_api(self):
        """Even without sim_capture or voice_capture in context, voice
        outbound must NOT call the WA HTTP API — there's no transport."""
        with patch.object(type(self.env['whatsapp.message']), 'send_whatsapp_message',
                          side_effect=_mock_send_ok) as mock_send:
            result = self.env['whatsapp.chatbot.message']._send_message_via_channel(
                chatbot=self.bot, step=self.greet,
                recipient_phone='+27600000801', body='Hello',
            )
        mock_send.assert_not_called()
        self.assertTrue(result['success'])

    def test_voice_capture_collects_bubble(self):
        """When env.context['voice_capture'] is a list, outbound appends to it."""
        captured = []
        env_ctx = self.env(context=dict(self.env.context, voice_capture=captured))
        env_ctx['whatsapp.chatbot.message']._send_message_via_channel(
            chatbot=self.bot, step=self.greet,
            recipient_phone='+27600000801', body='Hello there.',
        )
        self.assertEqual(len(captured), 1)
        bubble = captured[0]
        self.assertEqual(bubble['channel'], 'voice')
        self.assertEqual(bubble['coaching_notes'], 'Warm tone.')
        self.assertEqual(bubble['crm_action'], '[Open contact card.]')
        self.assertIn('Hello there.', bubble['body'])


# ──────────────────────────────────────────────────────────────────────────────
# Call session lifecycle
# ──────────────────────────────────────────────────────────────────────────────

@tagged('chatbot', 'voice', 'workspace', 'post_install', '-at_install')
class TestCallSessionLifecycle(WorkspaceFixtures):

    def test_create_session_then_first_turn_returns_script(self):
        sess = self.env['comm.voice.call.session'].create({
            'chatbot_id': self.bot.id,
            'contact_id': self.contact.id,
        })
        result = self.env['whatsapp.chatbot.message'].agent_turn(
            call_session_id=sess.id,
        )
        texts = [b.get('body') or b.get('text', '') for b in result['bubbles']]
        self.assertTrue(any('Hello there.' in t for t in texts))
        self.assertTrue(any("What's your name" in t for t in texts))
        self.assertFalse(result['terminate'])
        self.assertTrue(result['wait_for_input'])
        # session_state persisted on the record
        sess.invalidate_recordset(['session_state'])
        self.assertEqual(sess.session_state.get('current_step_id'), self.ask.id)

    def test_close_session_records_outcome_and_duration(self):
        sess = self.env['comm.voice.call.session'].create({
            'chatbot_id': self.bot.id,
            'contact_id': self.contact.id,
        })
        sess.action_close(outcome='resolved', notes='All good.')
        self.assertEqual(sess.outcome, 'resolved')
        self.assertEqual(sess.notes, 'All good.')
        self.assertTrue(sess.ended_at)
        self.assertGreaterEqual(sess.duration_seconds, 0)

    def test_agent_workspace_does_not_flag_records_as_simulator(self):
        """Workspace creates REAL records — never is_simulator=True."""
        sess = self.env['comm.voice.call.session'].create({
            'chatbot_id': self.bot.id,
            'contact_id': self.contact.id,
        })
        self.env['whatsapp.chatbot.message'].agent_turn(call_session_id=sess.id)
        self.contact.invalidate_recordset(['is_simulator'])
        self.assertFalse(
            self.contact.is_simulator,
            "Workspace contacts must NOT be flagged is_simulator — they're real customers."
        )


@tagged('chatbot', 'voice', 'workspace', 'post_install', '-at_install')
class TestSessionDisplayName(WorkspaceFixtures):

    def test_name_includes_partner_and_chatbot(self):
        sess = self.env['comm.voice.call.session'].create({
            'chatbot_id': self.bot.id,
            'contact_id': self.contact.id,
        })
        # compute fires after create, but partner_id is a related field that
        # may need a re-read to settle.
        sess.invalidate_recordset(['name', 'partner_id'])
        self.assertIn('Test Caller', sess.name)
        self.assertIn('Voice Test Script', sess.name)
