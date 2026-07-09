# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CommBotWebEmbedWizard(models.TransientModel):
    _name = 'comm.bot.web.embed.wizard'
    _description = 'Copy-paste embed snippet for the web widget'

    bot_id = fields.Many2one('comm.bot', required=True)
    base_url = fields.Char(readonly=True)
    embed_snippet = fields.Text(readonly=True, string='HTML snippet')
    iframe_snippet = fields.Text(readonly=True, string='Iframe snippet')
    direct_link = fields.Char(readonly=True)
    allowed_domains = fields.Text(
        string='Allowed embed domains',
        help='Edit here and save to update the bot\'s allowlist.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        bot_id = vals.get('bot_id') or self.env.context.get('default_bot_id')
        if bot_id:
            bot = self.env['comm.bot'].browse(bot_id)
            base = (self.env['ir.config_parameter'].sudo()
                     .get_param('web.base.url', '') or '').rstrip('/')
            vals.update({
                'bot_id': bot.id,
                'base_url': base,
                'allowed_domains': bot.web_allowed_domains or '',
                'embed_snippet': f'''<link rel="stylesheet" href="{base}/comm_chatbot_web/widget.css">
<script>
  window.COMM_CHATBOT_WEB = {{
    botId: {bot.id},
    baseUrl: "{base}"
  }};
</script>
<script src="{base}/comm_chatbot_web/widget.js"></script>''',
                'iframe_snippet': (
                    f'<iframe src="{base}/comm_chatbot_web/embed/{bot.id}"\n'
                    f'        width="400" height="600"\n'
                    f'        style="border: none; border-radius: 12px;"\n'
                    f'        title="Chat with {bot.name}"></iframe>'
                ),
                'direct_link': f'{base}/comm_chatbot_web/embed/{bot.id}',
            })
        return vals

    def action_save_allowlist(self):
        for wiz in self:
            wiz.bot_id.web_allowed_domains = wiz.allowed_domains or ''
        return {'type': 'ir.actions.act_window_close'}
