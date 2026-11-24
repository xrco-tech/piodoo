# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter


@tagged('post_install', '-at_install')
class TestVoiceIsVoip(TransactionCase):
    """Voice and VoIP calls are one channel, shown as Voice, and a flow can be
    marked as the calling script for a VoIP line."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Channel = cls.env['comm.channel'].with_context(active_test=False)
        cls.voip = Channel.search([('code', '=', 'voip')], limit=1)
        cls.voice = Channel.search([('code', '=', 'voice')], limit=1)
        cls.Bot = cls.env['comm.bot']

    def _unmerge(self):
        """Put things back to how they were before the merge ran."""
        self.voice.active = True
        self.voip.write({'name': 'VoIP Calls', 'supports_streaming': False})

    def test_installed_as_one_channel_called_voice(self):
        self.assertEqual(self.voip.name, 'Voice')
        self.assertFalse(self.voice.active, "the older Voice channel is put away")
        self.assertEqual(self.env['comm.channel'].get_by_code('voip'), self.voip)
        self.assertFalse(self.env['comm.channel'].get_by_code('voice'))

    def test_what_pointed_at_voice_moves_over(self):
        self._unmerge()
        both = self.Bot.create({'name': 'Both', 'channel_ids': [(6, 0, (self.voice | self.voip).ids)]})
        only = self.Bot.create({'name': 'Voice only', 'channel_ids': [(6, 0, self.voice.ids)]})
        step = self.env['comm.bot.step'].create({'bot_id': only.id, 'name': 'Hello', 'kind': 'message'})
        twice = self.env['comm.bot.step'].create({'bot_id': both.id, 'name': 'Hello', 'kind': 'message'})
        Override = self.env['comm.bot.step.channel.override']
        moved = Override.create({'step_id': step.id, 'channel_id': self.voice.id, 'body_override': 'spoken'})
        Override.create({'step_id': twice.id, 'channel_id': self.voice.id, 'body_override': 'old'})
        kept = Override.create({'step_id': twice.id, 'channel_id': self.voip.id, 'body_override': 'new'})
        trigger = self.env['comm.bot.trigger'].create(
            {'bot_id': only.id, 'channel_id': self.voice.id, 'kind': 'inbound_call'})

        self.assertTrue(self.env['comm.channel']._merge_voice_into_voip())
        self.assertEqual(only.channel_ids, self.voip)
        self.assertEqual(both.channel_ids, self.voip, "ticked on both: now ticked once")
        self.assertEqual(moved.channel_id, self.voip)
        self.assertEqual(twice.channel_override_ids, kept, "the VoIP wording wins")
        self.assertEqual(trigger.channel_id, self.voip)
        self.assertEqual(self.voip.name, 'Voice')
        self.assertTrue(self.voip.supports_streaming)
        self.assertFalse(self.voice.active)
        # Running it again changes nothing.
        self.assertFalse(self.env['comm.channel']._merge_voice_into_voip())

    def test_a_name_someone_chose_is_kept(self):
        self._unmerge()
        self.voip.name = 'Phone'
        self.env['comm.channel']._merge_voice_into_voip()
        self.assertEqual(self.voip.name, 'Phone')

    def test_a_flow_is_marked_for_a_voip_line(self):
        Account = self.env['comm.voip.account']
        line = Account.create({'name': 'Front desk', 'caller_id': '+27 10 000 0009'})
        bot = self.Bot.create({'name': 'Welcome call', 'channel_ids': [(6, 0, self.voip.ids)]})
        adapter = get_adapter('voip')()
        self.assertFalse(adapter.connections(self.env, bot)[0]['ok'])
        adapter.connect(self.env, bot, line.id, True)
        first = adapter.connections(self.env, bot)[0]
        self.assertEqual((first['name'], first['address'], first['model'], first['option_id']),
                         ('Front desk', '+27 10 000 0009', 'comm.voip.account', line.id))
        option = next(o for o in adapter.connect_options(self.env, bot) if o['id'] == line.id)
        self.assertTrue(option['connected'])
        # A copy of the flow is not marked for any line.
        self.assertFalse(bot.copy({'name': 'Welcome call two'}).voip_account_id)
        adapter.connect(self.env, bot, line.id, False)
        self.assertFalse(bot.voip_account_id)
