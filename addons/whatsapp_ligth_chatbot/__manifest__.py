# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Light Chatbot',
    'version': '18.0.1.0.0',
    'category': 'Tools',
    'summary': 'Chatbot functionality for WhatsApp Light',
    'description': """
WhatsApp Light Chatbot
======================

Chatbot building functionality for WhatsApp Light module.
Allows you to create conversational flows, handle user interactions,
and automate WhatsApp messaging.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'whatsapp_ligth', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/whatsapp_chatbot_views.xml',
        'views/whatsapp_chatbot_step_views.xml',
        'views/whatsapp_chatbot_contact_views.xml',
        'views/whatsapp_chatbot_message_views.xml',
        'views/whatsapp_chatbot_trigger_views.xml',
        'views/whatsapp_chatbot_variable_views.xml',
        'views/whatsapp_chatbot_answer_views.xml',
        'data/chatbot_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

