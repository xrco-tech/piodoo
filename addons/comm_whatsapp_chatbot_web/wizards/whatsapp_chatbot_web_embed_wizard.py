# -*- coding: utf-8 -*-
from odoo import models, fields, api


class WhatsappChatbotWebEmbedWizard(models.TransientModel):
    _name = 'whatsapp.chatbot.web.embed.wizard'
    _description = 'Copy-paste embed snippet for the WA chatbot web widget'

    chatbot_id = fields.Many2one('whatsapp.chatbot', required=True)
    base_url = fields.Char(readonly=True)
    embed_snippet = fields.Text(readonly=True, string='HTML snippet')
    iframe_snippet = fields.Text(readonly=True, string='Iframe snippet')
    direct_link = fields.Char(readonly=True)
    allowed_domains = fields.Text(string='Allowed embed domains')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        chatbot_id = (vals.get('chatbot_id')
                      or self.env.context.get('default_chatbot_id'))
        if chatbot_id:
            chatbot = self.env['whatsapp.chatbot'].browse(chatbot_id)
            base = (self.env['ir.config_parameter'].sudo()
                     .get_param('web.base.url', '') or '').rstrip('/')
            vals.update({
                'chatbot_id': chatbot.id,
                'base_url': base,
                'allowed_domains': chatbot.web_allowed_domains or '',
                'embed_snippet': f'''<link rel="stylesheet" href="{base}/comm_chatbot_web/widget.css">
<script>
  window.COMM_CHATBOT_WEB = {{
    botId: {chatbot.id},
    baseUrl: "{base}",
    endpointPrefix: "/comm_whatsapp_chatbot_web",
    botIdKey: "chatbot_id"
  }};
</script>
<script src="{base}/comm_chatbot_web/widget.js"></script>''',
                'iframe_snippet': (
                    f'<iframe src="{base}/comm_whatsapp_chatbot_web/embed/{chatbot.id}"\n'
                    f'        width="400" height="600"\n'
                    f'        style="border: none; border-radius: 12px;"\n'
                    f'        title="Chat with {chatbot.name}"></iframe>'
                ),
                'direct_link': f'{base}/comm_whatsapp_chatbot_web/embed/{chatbot.id}',
            })
        return vals

    def action_save_allowlist(self):
        for wiz in self:
            wiz.chatbot_id.web_allowed_domains = wiz.allowed_domains or ''
        return {'type': 'ir.actions.act_window_close'}
