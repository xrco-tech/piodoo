# -*- coding: utf-8 -*-
import types
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models import piodoo_ai_agent as mod

BUILT_IN = "You are a test assistant.\nBe brief."


@tagged('post_install', '-at_install')
class TestAgents(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Agent = cls.env['piodoo.ai.agent']
        cls.agent = cls.Agent.create({'key': 'test_bot', 'name': 'Tester', 'works_in': 'Here, There'})
        spec = {'addon': 'web', 'path': 'x', 'prompt': 'PROMPT', 'llm': 'LLM', 'llm_param': 'piodoo_ai.test_model',
                'usage': ('other', 'test_bot'), 'chat': False}
        fake = types.SimpleNamespace(PROMPT=BUILT_IN + "\n", LLM='claude-haiku-4-5-20251001')
        for target, value in (
                (patch.dict(mod.FEATURES, {'test_bot': spec}), None),
                (patch.object(type(cls.Agent), '_installed_addons', lambda self: {'web'}), None),
                (patch.object(type(cls.Agent), '_feature_module', lambda self: fake if self.key == 'test_bot' else None), None)):
            target.start()
            cls.addClassCleanup(target.stop)

    def test_model_label(self):
        self.assertEqual(mod.model_label('claude-haiku-4-5-20251001'), 'Haiku 4.5')
        self.assertEqual(mod.model_label('claude-opus-5-5'), 'Opus 5.5')
        self.assertEqual(mod.model_label('claude-opus-5'), 'Opus 5')
        self.assertEqual(mod.model_label('something-else'), 'something-else')
        self.assertEqual(mod.model_label(False), '')

    def test_wording_as_built_until_changed(self):
        self.assertEqual(self.Agent._instructions_for('test_bot', 'default'), 'default')
        self.assertEqual(self.Agent._instructions_for('nobody', 'default'), 'default')
        out = self.Agent.ui_agent(self.agent.id)
        self.assertEqual(out['instructions'], BUILT_IN)
        self.assertFalse(out['changed'])
        self.assertEqual(out['model'], 'Haiku 4.5')
        self.assertEqual(out['works'], ['Here', 'There'])

    def test_save_keeps_versions_and_takes_effect(self):
        out = self.Agent.ui_save(self.agent.id, "  Be very brief.  ")
        self.assertTrue(out['changed'])
        self.assertEqual(out['instructions'], "Be very brief.")
        self.assertEqual(self.Agent._instructions_for('test_bot', 'default'), "Be very brief.")
        # Saving the same text again keeps nothing new.
        self.Agent.ui_save(self.agent.id, "Be very brief.")
        self.assertEqual(len(self.agent._versions()), 1)
        self.Agent.ui_save(self.agent.id, "Be brief and kind.")
        history = self.Agent.ui_history(self.agent.id)
        self.assertEqual([row['text'] for row in history], ["Be brief and kind.", "Be very brief."])
        # An older version can be used again; that is a new save.
        out = self.Agent.ui_restore(history[1]['id'])
        self.assertEqual(out['instructions'], "Be very brief.")
        self.assertEqual(out['versions'], 3)

    def test_back_to_as_built(self):
        self.Agent.ui_save(self.agent.id, "Mine.")
        out = self.Agent.ui_reset(self.agent.id)
        self.assertFalse(out['changed'])
        self.assertEqual(out['instructions'], BUILT_IN)
        self.assertFalse(self.agent.instructions)
        self.assertTrue(self.agent._versions()[0].as_built)
        self.assertEqual(self.Agent._instructions_for('test_bot', 'default'), 'default')
        # Typing the built-in wording back in is the same thing.
        self.Agent.ui_save(self.agent.id, "Mine.")
        self.assertFalse(self.Agent.ui_save(self.agent.id, BUILT_IN)['changed'])

    def test_empty_wording_is_refused(self):
        with self.assertRaises(UserError):
            self.Agent.ui_save(self.agent.id, "   ")

    def test_model_setting_wins(self):
        self.env['ir.config_parameter'].set_param('piodoo_ai.test_model', 'claude-opus-5-5')
        self.assertEqual(self.Agent.ui_agent(self.agent.id)['model'], 'Opus 5.5')

    def test_home_shows_only_installed(self):
        home = self.Agent.ui_home()
        self.assertEqual([card['key'] for card in home['agents']], ['test_bot'])
        self.assertEqual(home['works'], ['Here', 'There'])
        with patch.object(type(self.Agent), '_installed_addons', lambda self: set()):
            self.assertEqual(self.Agent.ui_home()['agents'], [])
            with self.assertRaises(UserError):
                self.Agent.ui_agent(self.agent.id)

    def test_only_admins(self):
        user = new_test_user(self.env, login='pai_user', groups='base.group_user')
        Agent = self.Agent.with_user(user)
        for call in (lambda: Agent.ui_home(), lambda: Agent.ui_agent(self.agent.id),
                     lambda: Agent.ui_save(self.agent.id, "Hello"), lambda: Agent.ui_history(self.agent.id)):
            with self.assertRaises(AccessError):
                call()
        # The assistant itself still gets its wording, whoever is using it.
        self.Agent.ui_save(self.agent.id, "Mine.")
        self.assertEqual(Agent._instructions_for('test_bot', 'default'), "Mine.")

    def test_no_chat_with_a_task_agent(self):
        with self.assertRaises(UserError):
            self.Agent.ui_chats(self.agent.id)

    def test_seeded_agents_match_the_features(self):
        keys = set(self.Agent.search([]).mapped('key')) - {'test_bot'}
        self.assertEqual(keys, set(mod.FEATURES) - {'test_bot'})


@tagged('post_install', '-at_install')
class TestAgentTabs(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from ..models import piodoo_ai_tabs as tabs
        cls.tabs = tabs
        cls.Agent = cls.env['piodoo.ai.agent']
        cls.agent = cls.Agent.create({'key': 'test_bot', 'name': 'Tester'})
        spec = {'addon': 'web', 'path': 'x', 'prompt': 'PROMPT', 'llm': 'LLM', 'llm_param': False,
                'usage': ('other', 'test_bot'), 'chat': True}
        extra = {'skills': [('make', "Making", 'makes', "Makes things.", ['create_thing', 'update_thing']),
                            ('look', "Looking", 'reads', "Looks.", ['list_things'])],
                 'asks_first': True, 'library': False, 'crons': [('base.autovacuum_job', "Tidy up", '')],
                 'places': ["Here"], 'who': "Everyone"}
        fake = types.SimpleNamespace(PROMPT=BUILT_IN, LLM='claude-haiku-4-5-20251001')
        for target in (
                patch.dict(mod.FEATURES, {'test_bot': spec}),
                patch.dict(tabs.TABS, {'test_bot': extra}),
                patch.object(type(cls.Agent), '_installed_addons', lambda self: {'web'}),
                patch.object(type(cls.Agent), '_feature_module', lambda self: fake if self.key == 'test_bot' else None),
                patch.object(type(cls.Agent), '_chat_blocked', lambda self: False)):
            target.start()
            cls.addClassCleanup(target.stop)
        cls.TOOLS = [{'name': 'create_thing'}, {'name': 'update_thing'}, {'name': 'list_things'}, {'name': 'other'}]

    def test_nothing_set_is_as_built(self):
        self.assertEqual(self.Agent._tools_for('test_bot', self.TOOLS), self.TOOLS)
        self.assertEqual(self.Agent._tools_for('nobody', self.TOOLS), self.TOOLS)
        self.assertTrue(self.Agent._tool_allowed('test_bot', 'create_thing'))
        self.assertEqual(self.Agent._model_for('test_bot', 'x'), 'x')
        self.assertEqual(self.Agent._model_for('nobody', 'x'), 'x')
        self.assertIsNone(self.Agent._library_only('test_bot'))
        self.assertEqual(self.Agent._stopped('test_bot'), '')
        self.assertEqual(self.Agent._stopped('nobody'), '')
        self.assertEqual(self.Agent._answer_cap('test_bot'), 0.0)
        self.assertEqual(self.Agent._instructions_for('test_bot', 'default'), 'default')

    def test_skill_off_takes_its_tools_away(self):
        out = self.Agent.ui_set_skill(self.agent.id, 'make', False)
        self.assertEqual([(s['key'], s['on']) for s in out['tabs']['skills']], [('make', False), ('look', True)])
        self.assertEqual([t['name'] for t in self.Agent._tools_for('test_bot', self.TOOLS)], ['list_things', 'other'])
        self.assertFalse(self.Agent._tool_allowed('test_bot', 'update_thing'))
        self.assertTrue(self.Agent._tool_allowed('test_bot', 'list_things'))
        self.assertIn('Making', self.Agent._instructions_for('test_bot', 'default'))
        self.Agent.ui_set_skill(self.agent.id, 'make', True)
        self.assertEqual(self.Agent._tools_for('test_bot', self.TOOLS), self.TOOLS)
        self.assertEqual(self.Agent._instructions_for('test_bot', 'default'), 'default')
        with self.assertRaises(UserError):
            self.Agent.ui_set_skill(self.agent.id, 'nope', False)

    def test_every_listed_tool_is_in_one_skill_only(self):
        for key, extra in self.tabs.TABS.items():
            tools = [tool for skill in extra['skills'] for tool in skill[4]]
            self.assertEqual(len(tools), len(set(tools)), key)

    def test_timer_switch(self):
        cron = self.env.ref('base.autovacuum_job')
        out = self.Agent.ui_set_cron(self.agent.id, cron.id, False)
        self.assertFalse(cron.active)
        self.assertFalse(out['tabs']['crons'][0]['active'])
        self.Agent.ui_set_cron(self.agent.id, cron.id, True)
        self.assertTrue(cron.active)
        # Only the agent's own timers, and never a locked one.
        other = self.env['ir.cron'].search([('id', '!=', cron.id)], limit=1)
        with self.assertRaises(UserError):
            self.Agent.ui_set_cron(self.agent.id, other.id, False)
        with patch.dict(self.tabs.TABS['test_bot'], {'crons': [('base.autovacuum_job', "Tidy up", "Shared.")]}):
            with self.assertRaises(UserError):
                self.Agent.ui_set_cron(self.agent.id, cron.id, False)
        self.assertTrue(cron.active)

    def test_model_choice(self):
        with patch.object(type(self.Agent), '_model_options', lambda self: ['claude-opus-5-5']):
            out = self.Agent.ui_set_limits(self.agent.id, 'claude-opus-5-5', 0, 0)
            self.assertEqual(out['model'], 'Opus 5.5')
            self.assertEqual(self.Agent._model_for('test_bot', 'x'), 'claude-opus-5-5')
            with self.assertRaises(UserError):
                self.Agent.ui_set_limits(self.agent.id, 'claude-made-up-9', 0, 0)
            out = self.Agent.ui_set_limits(self.agent.id, '', 0, 0)
            self.assertEqual(out['model'], 'Haiku 4.5')
            self.assertEqual(self.Agent._model_for('test_bot', 'x'), 'x')

    def test_monthly_limit_stops_the_agent(self):
        spent = {'value': 4.0}
        with patch.object(type(self.Agent), '_month_spend', lambda self: spent['value']):
            out = self.Agent.ui_set_limits(self.agent.id, '', 5, 0.5)
            self.assertEqual(out['tabs']['limits']['monthly_cap'], 5)
            self.assertFalse(out['stopped'])
            self.assertEqual(self.Agent._stopped('test_bot'), '')
            self.assertEqual(self.Agent._answer_cap('test_bot'), 0.5)
            spent['value'] = 5.0
            self.assertIn('Tester', self.Agent._stopped('test_bot'))
            self.assertTrue(self.Agent.ui_agent(self.agent.id)['stopped'])
            self.Agent.ui_set_limits(self.agent.id, '', 0, 0)
            self.assertEqual(self.Agent._stopped('test_bot'), '')
            with self.assertRaises(UserError):
                self.Agent.ui_set_limits(self.agent.id, '', -1, 0)
        # Without billing a limit could never be reached, so it is refused.
        with patch.object(type(self.Agent), '_month_spend', lambda self: None):
            with self.assertRaises(UserError):
                self.Agent.ui_set_limits(self.agent.id, '', 5, 0)

    def test_knowledge_needs_the_library(self):
        self.assertEqual(self.Agent.ui_agent(self.agent.id)['tabs']['knowledge'], {'reads': False})
        with self.assertRaises(UserError):
            self.Agent.ui_knowledge_options(self.agent.id)

    def test_tabs_are_for_admins(self):
        user = new_test_user(self.env, login='pai_tab_user', groups='base.group_user')
        Agent = self.Agent.with_user(user)
        for call in (lambda: Agent.ui_set_skill(self.agent.id, 'make', False),
                     lambda: Agent.ui_set_cron(self.agent.id, self.env.ref('base.autovacuum_job').id, False),
                     lambda: Agent.ui_set_limits(self.agent.id, '', 1, 0)):
            with self.assertRaises(AccessError):
                call()
