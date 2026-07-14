# -*- coding: utf-8 -*-

from odoo import api, models, fields

CONFIG_PARAM = 'whatsapp.anthropic_api_key'


class ContactCentreWhatsAppConfig(models.Model):
    _inherit = 'contact.centre.whatsapp.config'

    # NOTE: `config_parameter=` on a plain field only auto-syncs to
    # ir.config_parameter for res.config.settings models - this is a
    # regular model, so that kwarg is silently inert (it's what produced
    # the "unknown parameter 'config_parameter'" warning on every deploy).
    # The pre-existing `open_ai_api_key` field has the same latent bug;
    # out of scope to fix here since nothing reads it. Syncing explicitly
    # below instead of relying on the kwarg.
    anthropic_api_key = fields.Char('Anthropic API Key', password=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._sync_anthropic_api_key()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'anthropic_api_key' in vals:
            for record in self:
                record._sync_anthropic_api_key()
        return result

    def _sync_anthropic_api_key(self):
        self.env['ir.config_parameter'].sudo().set_param(CONFIG_PARAM, self.anthropic_api_key or '')
