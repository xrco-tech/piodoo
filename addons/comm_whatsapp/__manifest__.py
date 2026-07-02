# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp CE (Community Edition)',
    'version': '18.0.1.0.67',
    'category': 'Tools',
    'summary': 'WhatsApp Community Edition Integration Module',
    'description': """
WhatsApp CE (Community Edition)
================================

A lightweight WhatsApp integration module for Odoo Community Edition.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/whatsapp_groups.xml',
        'security/ir.model.access.csv',
        'views/whatsapp_account_views.xml',
        'views/res_config_settings_views.xml',
        'views/whatsapp_templates.xml',
        'views/whatsapp_message_views.xml',
        'views/whatsapp_message_reply_wizard_views.xml',
        'views/whatsapp_template_views.xml',
        'views/whatsapp_flow_screen_views.xml',
        'views/whatsapp_flow_component_views.xml',
        'views/whatsapp_flow_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_whatsapp/static/src/xml/flow_canvas.xml',
            'comm_whatsapp/static/src/css/flow_canvas.css',
            'comm_whatsapp/static/src/js/flow_canvas.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

