# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Light Chatbot',
    'version': '18.0.1.0.9',
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
    'depends': ['base', 'web', 'comm_whatsapp', 'comm_sms', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/whatsapp_chatbot_ussd_account_views.xml',
        'views/voice_call_session_views.xml',
        'views/whatsapp_chatbot_views.xml',
        'views/whatsapp_chatbot_step_views.xml',
        'views/whatsapp_chatbot_contact_views.xml',
        'views/whatsapp_chatbot_message_views.xml',
        'views/whatsapp_chatbot_trigger_views.xml',
        'views/whatsapp_chatbot_variable_views.xml',
        'views/whatsapp_chatbot_answer_views.xml',
        'views/whatsapp_message_views.xml',
        'views/chatbot_steps_templates.xml',
        'data/chatbot_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_whatsapp_chatbot/static/src/xml/chatbot_flow_action.xml',
            'comm_whatsapp_chatbot/static/src/css/chatbot_flow_action.css',
            'comm_whatsapp_chatbot/static/src/js/chatbot_flow_widget.js',
            'comm_whatsapp_chatbot/static/src/xml/agent_workspace.xml',
            'comm_whatsapp_chatbot/static/src/css/agent_workspace.css',
            'comm_whatsapp_chatbot/static/src/js/agent_workspace.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

