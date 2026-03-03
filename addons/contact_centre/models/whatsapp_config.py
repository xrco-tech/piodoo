# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreWhatsAppConfig(models.Model):
    _name = 'contact.centre.whatsapp.config'
    _description = 'WhatsApp Configuration'

    name = fields.Char('Configuration Name', required=True)
    active = fields.Boolean('Active', default=True)

    # OpenAI / AI agent settings
    open_ai_api_key = fields.Char('OpenAI API Key', password=True,
                                  config_parameter='whatsapp.open_ai_api_key')
    external_trigger_api_key = fields.Char('External Trigger / Webhook Verify Token',
                                           config_parameter='whatsapp.external_trigger_api_key')

    # Auto-answer calls
    auto_answer_whatsapp_calls = fields.Boolean(
        'Auto-Answer WhatsApp Calls',
        config_parameter='whatsapp.auto_answer_calls',
        default=True,
        help='Automatically answer incoming WhatsApp calls and open VoIP widget'
    )
