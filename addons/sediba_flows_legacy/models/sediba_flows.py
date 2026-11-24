# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import UserError


class SedibaFlows(models.AbstractModel):
    _inherit = 'sediba.flows'

    @api.model
    def home(self):
        res = super().home()
        Old = self.env['whatsapp.chatbot']
        if not Old.has_access('read'):
            return res
        flows = {b.legacy_chatbot_id.id: b.id for b in self.env['comm.bot'].search(
            [('legacy_chatbot_id', '!=', False)], order='id desc')}
        channels = dict(Old._fields['channel']._description_selection(self.env))
        statuses = dict(Old._fields['status']._description_selection(self.env))
        res['legacy'] = [{
            'id': c.id,
            'name': c.name,
            'channel': channels.get(c.channel, c.channel),
            'status': statuses.get(c.status, c.status),
            'steps': len(c.step_ids),
            'flow_id': flows.get(c.id, False),
        } for c in Old.search([])]
        return res

    def _duplicate_defaults(self, bot, name):
        # The copy keeps the notes (its steps are the same) but is not the
        # older bot's flow: "Open its flow" stays with the original.
        return dict(super()._duplicate_defaults(bot, name),
                    legacy_chatbot_id=False, import_notes=bot.import_notes)

    def _card_attention(self, bot):
        res = super()._card_attention(bot)
        notes = len([n for n in (bot.import_notes or '').split('\n') if n])
        if notes == 1:
            res.append(_("1 note from when it was brought over"))
        elif notes:
            res.append(_("%s notes from when it was brought over", notes))
        return res

    @api.model
    def load(self, bot_id):
        res = super().load(bot_id)
        bot = self.env['comm.bot'].browse(bot_id)
        res['flow']['notes'] = [n for n in (bot.import_notes or '').split('\n') if n]
        res['flow']['legacy_name'] = bot.legacy_chatbot_id.name or ''
        return res

    @api.model
    def import_legacy(self, chatbot_id):
        chatbot = self.env['whatsapp.chatbot'].browse(chatbot_id).exists()
        if not chatbot:
            raise UserError(_("That bot no longer exists."))
        return self.env['sediba.flows.importer'].import_bot(chatbot).id
