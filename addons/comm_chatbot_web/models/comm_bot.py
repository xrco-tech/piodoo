# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CommBot(models.Model):
    _inherit = 'comm.bot'

    web_allowed_domains = fields.Text(
        string='Web widget: allowed embed domains',
        help='Newline-separated list of origins allowed to embed the widget '
             '(iframe) or open sessions cross-origin. Example:\n'
             'https://example.com\n'
             'https://www.example.com\n'
             'Leave empty for same-origin only (Odoo host).')

    def _web_allowed_domain_list(self):
        self.ensure_one()
        raw = self.web_allowed_domains or ''
        return [d.strip().rstrip('/') for d in raw.splitlines() if d.strip()]

    def _web_origin_allowed(self, origin):
        """Check whether an Origin/Referer is allowed to embed / connect."""
        self.ensure_one()
        if not origin:
            return True   # same-origin requests have no Origin header
        origin = origin.rstrip('/')
        base = (self.env['ir.config_parameter'].sudo()
                 .get_param('web.base.url', '') or '').rstrip('/')
        if origin == base:
            return True
        return origin in self._web_allowed_domain_list()

    def action_open_web_embed_code(self):
        """Open a wizard with the ready-to-paste embed snippet."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Embed code — {self.name}',
            'res_model': 'comm.bot.web.embed.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_bot_id': self.id},
        }
