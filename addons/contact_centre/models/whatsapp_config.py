# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreWhatsAppConfig(models.Model):
    _name = 'contact.centre.whatsapp.config'
    _description = 'WhatsApp Configuration'

    name = fields.Char('Configuration Name', required=True)
    active = fields.Boolean('Active', default=True)

    # Link to native whatsapp.account
    wa_account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account',
                                    help='The WhatsApp Business Account used for sending messages')
    account_id = fields.Char('Meta Business Account ID',
                              related='wa_account_id.account_uid', readonly=True)

    # OpenAI / AI agent settings (from whatsapp_custom)
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
