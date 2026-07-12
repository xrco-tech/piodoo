# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreWhatsAppConfig(models.Model):
    _inherit = 'contact.centre.whatsapp.config'

    anthropic_api_key = fields.Char('Anthropic API Key', password=True,
                                    config_parameter='whatsapp.anthropic_api_key')
