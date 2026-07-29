# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — Email Adapter',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Email channel adapter for comm_chatbot (via mail.mail)',
    'author': 'XR Co.',
    'license': 'LGPL-3',
    # Mirrors the comm_chatbot_sms adapter pattern. Email has no pre-existing
    # source module in the repo, so this is the new channel adapter UCX needs
    # for the Conversations > Email item.
    'depends': ['comm_chatbot', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_channel_data.xml',
    ],
    'installable': True,
    'auto_install': False,
}
