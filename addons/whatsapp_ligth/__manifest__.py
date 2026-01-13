# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Light',
    'version': '18.0.1.0.1',
    'category': 'Tools',
    'summary': 'WhatsApp Light Integration Module',
    'description': """
WhatsApp Light
==============

A lightweight WhatsApp integration module for Odoo.
    """,
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/whatsapp_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

