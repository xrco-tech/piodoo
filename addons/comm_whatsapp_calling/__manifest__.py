# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Calling (comm_whatsapp)',
    'version': '18.0.1.12.0',
    'category': 'Communications',
    'summary': 'WhatsApp Cloud API Calling: make and receive calls with comm_whatsapp',
    'description': """
WhatsApp Calling for Odoo Community
===================================
Enables receiving and making WhatsApp voice calls when using comm_whatsapp.

- Handles webhook events for the `calls` field
- Creates call logs and links to contacts
- Sends pre_accept/accept/decline to Meta Graph API
- Optional: integrate with contact_centre for call history and agent UI

Requires: Meta App with Calling enabled, webhook subscribed to `calls`.
See WHATSAPP_CALLING_PLAN.md for Meta API details and WebRTC options.
    """,
    'author': 'If I Could Code (Org)',
    'license': 'LGPL-3',
    'depends': [
        'comm_whatsapp',
        'mail',
    ],
    'data': [
        'security/whatsapp_call_recording_groups.xml',
        'security/ir.model.access.csv',
        'views/comm_disposition_views.xml',
        'views/whatsapp_call_log_views.xml',
        'views/whatsapp_call_team_views.xml',
        'views/whatsapp_call_permission_views.xml',
        'views/whatsapp_account_views.xml',
        'views/whatsapp_call_routing_rule_views.xml',
        'views/comm_whatsapp_monitor_views.xml',
        'views/res_partner_views.xml',
        'data/backfill_outbound_timestamps.xml',
        'data/purge_recordings_cron.xml',
        'data/backfill_incoming_call_accounts.xml',
        'data/backfill_call_permissions.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_whatsapp_calling/static/src/scss/phone_card.scss',
            'comm_whatsapp_calling/static/src/css/call_log_kanban.css',
            'comm_whatsapp_calling/static/src/xml/phone_card.xml',
            'comm_whatsapp_calling/static/src/js/incoming_call_popup.js',
            'comm_whatsapp_calling/static/src/js/phone_card.js',
            'comm_whatsapp_calling/static/src/js/call_monitor.js',
            'comm_whatsapp_calling/static/src/js/dial_action.js',
        ],
        'web.assets_web_dark': [
            'comm_whatsapp_calling/static/src/scss/phone_card.dark.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
