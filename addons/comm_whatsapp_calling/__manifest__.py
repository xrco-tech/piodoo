# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Calling (comm_whatsapp)',
    'version': '18.0.1.0.0',
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
        'security/ir.model.access.csv',
        'views/whatsapp_call_log_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_whatsapp_calling/static/src/css/incoming_call_popup.css',
            'comm_whatsapp_calling/static/src/css/systray_whatsapp_calls.css',
            'comm_whatsapp_calling/static/src/js/incoming_call_popup.js',
            'comm_whatsapp_calling/static/src/js/systray_whatsapp_calls.js',
            'comm_whatsapp_calling/static/src/xml/systray_whatsapp_calls.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
