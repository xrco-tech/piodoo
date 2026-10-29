# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work in UCX',
    'version': '18.0.1.1.0',
    'category': 'Human Resources/Recruitment',
    'summary': "Show Chat2Work USSD, WhatsApp, CV-link and CV-page activity in the UCX workspace",
    'description': """
Chat2Work in UCX
================
Writes Chat2Work activity to the candidate's UCX conversation, next to their
SMS, WhatsApp and calls:

- each USSD session, as one entry with the choices made and the result;
- each WhatsApp sign-up chat, message by message;
- each CV link sent by WhatsApp or SMS (WhatsApp delivery status kept current);
- CV uploads, built CVs and help requests from the CV page.

Only candidates are logged, so nothing is kept for a caller who never gives
consent. ID numbers never appear in the log.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['chat2work', 'comm_chatbot'],
    'data': [],
    'auto_install': True,
    'installable': True,
}
