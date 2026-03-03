# -*- coding: utf-8 -*-
{
    'name': 'Contact Centre',
    'version': '18.0.1.0.0',
    'category': 'Customer Relationship Management',
    'summary': 'Unified SMS and WhatsApp Contact Centre',
    'description': """
Contact Centre Module
=====================
Unified contact centre for managing SMS and WhatsApp communications.

Features:
---------
* Unified messaging interface for SMS and WhatsApp
* Contact management with communication history
* Campaign management (inbound and outbound)
* Agent tools (dynamic scripts)
* Automated replies and chatbot integration
* Template management
* Configuration for WhatsApp and SMS providers
    """,
    'author': 'If I Could Code (Org)',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'mail',
        'utm',
        'web',
        'sms',                  # Odoo SMS framework (sms.sms model)
        'comm_sms',             # InfoBip SMS integration
        'comm_whatsapp',        # Community WhatsApp (whatsapp.message, whatsapp.template, etc.)
        'comm_whatsapp_chatbot',  # Community WhatsApp chatbot (whatsapp.chatbot, etc.)
    ],
    'data': [
        'security/contact_centre_security.xml',
        'security/ir.model.access.csv',
        'data/contact_centre_data.xml',
        'views/contact_centre_dashboard_views.xml',
        'views/contact_centre_contact_views.xml',
        'views/contact_centre_message_views.xml',
        'views/contact_centre_campaign_views.xml',
        'views/contact_centre_script_views.xml',
        'views/contact_centre_automation_views.xml',
        'views/contact_centre_chatbot_views.xml',
        'views/whatsapp_config_views.xml',
        'views/sms_config_views.xml',
        'views/email_config_views.xml',
        'views/contact_centre_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'contact_centre/static/src/dashboard/dashboard.js',
            'contact_centre/static/src/dashboard/dashboard.xml',
            'contact_centre/static/src/dashboard/dashboard.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
