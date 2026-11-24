# -*- coding: utf-8 -*-
from odoo import api, models


class CommChannel(models.Model):
    _inherit = 'comm.channel'

    @api.model
    def _merge_voice_into_voip(self):
        """Voice and VoIP calls are one thing: a call over the VoIP line. The
        VoIP channel is the one calls are really logged on, so it stays, under
        the name people use, "Voice". The older Voice channel, which no call
        ever ran on, is put away, and whatever pointed at it is moved over.
        Safe to run again."""
        Channel = self.with_context(active_test=False)
        voip = Channel.search([('code', '=', 'voip')], limit=1)
        voice = Channel.search([('code', '=', 'voice')], limit=1)
        if not voip:
            return False
        if voip.name == 'VoIP Calls':
            voip.name = 'Voice'
        if not voice or not voice.active:
            return False
        bots = self.env['comm.bot'].with_context(active_test=False).search(
            [('channel_ids', 'in', voice.ids)])
        for bot in bots:
            bot.channel_ids = [(3, voice.id), (4, voip.id)]
        Override = self.env['comm.bot.step.channel.override']
        for override in Override.search([('channel_id', '=', voice.id)]):
            # One wording per step and channel: the VoIP one wins if both exist.
            if Override.search_count([('step_id', '=', override.step_id.id),
                                      ('channel_id', '=', voip.id)]):
                override.unlink()
            else:
                override.channel_id = voip
        self.env['comm.bot.trigger'].with_context(active_test=False).search(
            [('channel_id', '=', voice.id)]).write({'channel_id': voip.id})
        self.env['comm.bot.step'].search(
            [('channel_switch_target_id', '=', voice.id)]).write(
            {'channel_switch_target_id': voip.id})
        if voice.supports_streaming and not voip.supports_streaming:
            voip.supports_streaming = True
        voice.active = False
        return True
