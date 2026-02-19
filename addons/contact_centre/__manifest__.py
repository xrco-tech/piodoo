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
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'mail',
        'utm',
        'web',
    ],
    'data': [
        'security/contact_centre_security.xml',
        'security/ir.model.access.csv',
        'data/contact_centre_data.xml',
        'views/contact_centre_contact_views.xml',
        'views/contact_centre_message_views.xml',
        'views/contact_centre_campaign_views.xml',
        'views/contact_centre_script_views.xml',
        'views/contact_centre_automation_views.xml',
        'views/whatsapp_config_views.xml',
        'views/sms_config_views.xml',
        'views/contact_centre_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
