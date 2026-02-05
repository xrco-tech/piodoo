# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # OAuth / Meta App
    whatsapp_ligth_app_id = fields.Char(
        string='Meta App ID',
        config_parameter='whatsapp_ligth.app_id',
        help='Facebook/Meta App ID from developers.facebook.com',
    )
    whatsapp_ligth_app_secret = fields.Char(
        string='Meta App Secret',
        config_parameter='whatsapp_ligth.app_secret',
        help='Facebook/Meta App Secret',
    )
    whatsapp_ligth_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        config_parameter='whatsapp_ligth.redirect_uri',
        help='Must match the URI configured in Meta App. Default: {base_url}whatsapp/auth/callback',
    )
    whatsapp_ligth_scope = fields.Char(
        string='OAuth Scope',
        config_parameter='whatsapp_ligth.scope',
        default='whatsapp_business_management,whatsapp_business_messaging',
        help='Comma-separated OAuth scopes (e.g. whatsapp_business_management,whatsapp_business_messaging)',
    )

    # Webhook
    whatsapp_ligth_webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='whatsapp_ligth.webhook_verify_token',
        help='Token you set in Meta App for webhook URL verification (GET request)',
    )

    # Tokens (set by OAuth callback; can be overridden manually)
    whatsapp_ligth_access_token = fields.Char(
        string='Access Token',
        config_parameter='whatsapp_ligth.access_token',
        help='Current access token. Usually set automatically after OAuth; edit only if needed.',
    )
    whatsapp_ligth_long_lived_token = fields.Char(
        string='Long-Lived Token',
        config_parameter='whatsapp_ligth.long_lived_token',
        help='Long-lived token (60 days). Set automatically after OAuth.',
    )

    # From webhook or set manually
    whatsapp_ligth_business_account_id = fields.Char(
        string='Business Account ID',
        config_parameter='whatsapp_ligth.business_account_id',
        help='WhatsApp Business Account ID. Can be set automatically from the first webhook.',
    )
    whatsapp_ligth_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='whatsapp_ligth.phone_number_id',
        help='Phone Number ID used to send/receive. Can be set automatically from the first webhook.',
    )
