# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Light',
    'version': '18.0.1.0.30',
    'category': 'Tools',
    'summary': 'WhatsApp Light Integration Module',
    'description': """
WhatsApp Light
==============

A lightweight WhatsApp integration module for Odoo.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/whatsapp_groups.xml',
        'security/ir.model.access.csv',
        'views/whatsapp_templates.xml',
        'views/whatsapp_message_views.xml',
        'views/whatsapp_message_reply_wizard_views.xml',
        'views/whatsapp_template_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

