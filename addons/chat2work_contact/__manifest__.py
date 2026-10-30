# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work Contact Actions',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Call and message candidates from their record',
    'description': """
Buttons on the candidate form: call on WhatsApp, call by VoIP with the agent's
softphone, and send a WhatsApp message or SMS, typed or from a template. Uses
the existing calling services and senders. Every contact is noted on the
candidate.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work', 'comm_dialer', 'sms'],
    'data': [
        'security/ir.model.access.csv',
        'data/chat2work_contact_data.xml',
        'wizards/chat2work_message_views.xml',
        'views/chat2work_candidate_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'chat2work_contact/static/src/js/voip_dial.js',
        ],
    },
    'installable': True,
}
