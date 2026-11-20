# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .common import ChatbotTestCase


@tagged('comm_chatbot', 'post_install', '-at_install')
class TestLlmSediba(ChatbotTestCase):
    """An AI step answers from Sediba only when it is ticked to, and only
    from what Sediba allowed for the assistants."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.step_ai = cls.env['comm.bot.step'].create({
            'bot_id': cls.bot.id, 'name': 'answer', 'kind': 'llm', 'llm_system_prompt': 'Help the caller.'})
        cls.Llm = cls.env['comm.chatbot.llm']

    def setUp(self):
        super().setUp()
        if 'sediba.assistant' not in self.env:
            self.skipTest("sediba is not installed")

    def test_off_until_ticked(self):
        self.assertFalse(self.Llm._build_tools(self.step_ai))
        self.assertIn('error', self.Llm._execute_tool(self.step_ai, 'look_up_reference', {'question': 'x'}, None))
        self.step_ai.llm_use_sediba = True
        self.assertEqual([tool['name'] for tool in self.Llm._build_tools(self.step_ai)], ['look_up_reference'])

    def test_it_reads_what_sediba_allowed(self):
        Doc = self.env['sediba.doc']
        allowed = Doc.create({'name': 'About Zebraworks', 'body': '<p>Zebraworks is free for job seekers.</p>'})
        kept = Doc.create({'name': 'Zebraworks staff notes', 'body': '<p>Zebraworks internal.</p>', 'ai_allowed': False})
        (allowed | kept).action_publish()
        Doc.create({'name': 'Zebraworks plans', 'body': '<p>Zebraworks draft.</p>'})
        self.step_ai.llm_use_sediba = True
        result = self.Llm._execute_tool(self.step_ai, 'look_up_reference', {'question': 'Zebraworks'}, None)
        self.assertEqual(result['used'], ['About Zebraworks'])
