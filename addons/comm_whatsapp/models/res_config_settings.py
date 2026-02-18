# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # OAuth / Meta App
    comm_whatsapp_app_id = fields.Char(
        string='Meta App ID',
        config_parameter='comm_whatsapp.app_id',
        help='Facebook/Meta App ID from developers.facebook.com',
    )
    comm_whatsapp_app_secret = fields.Char(
        string='Meta App Secret',
        config_parameter='comm_whatsapp.app_secret',
        help='Facebook/Meta App Secret',
    )
    comm_whatsapp_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        config_parameter='comm_whatsapp.redirect_uri',
        help='Must match the URI configured in Meta App. Default: {base_url}whatsapp/auth/callback',
    )
    comm_whatsapp_scope = fields.Char(
        string='OAuth Scope',
        config_parameter='comm_whatsapp.scope',
        default='whatsapp_business_management,whatsapp_business_messaging',
        help='Comma-separated OAuth scopes (e.g. whatsapp_business_management,whatsapp_business_messaging)',
    )

    # Webhook
    comm_whatsapp_webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='comm_whatsapp.webhook_verify_token',
        help='Token you set in Meta App for webhook URL verification (GET request)',
    )

    # Tokens (set by OAuth callback; can be overridden manually)
    comm_whatsapp_access_token = fields.Char(
        string='Access Token',
        config_parameter='comm_whatsapp.access_token',
        help='Current access token. Usually set automatically after OAuth; edit only if needed.',
    )
    comm_whatsapp_long_lived_token = fields.Char(
        string='Long-Lived Token',
        config_parameter='comm_whatsapp.long_lived_token',
        help='Long-lived token (60 days). Set automatically after OAuth.',
    )

    # From webhook or set manually
    comm_whatsapp_business_account_id = fields.Char(
        string='Business Account ID',
        config_parameter='comm_whatsapp.business_account_id',
        help='WhatsApp Business Account ID. Can be set automatically from the first webhook.',
    )
    comm_whatsapp_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='comm_whatsapp.phone_number_id',
        help='Phone Number ID used to send/receive. Can be set automatically from the first webhook.',
    )
