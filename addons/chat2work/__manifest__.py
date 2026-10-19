# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work',
    'version': '18.0.1.1.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Job openings, interview slots and bookings for the Chat2Work service',
    'description': """
Chat2Work
=========
Minimal recruitment data behind the Chat2Work omnichannel service (USSD /
WhatsApp / SMS): job openings, bookable interview slots, and the interview
bookings candidates make. The USSD chatbot reads these live so the menus are
dynamic.

The Chat2Work USSD flow (spec v1.0: create profile, update status, request
callback) runs on any USSD account whose Flow Engine is set to Chat2Work.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'contacts', 'sms', 'comm_whatsapp_chatbot'],
    'data': [
        'security/ir.model.access.csv',
        'data/chat2work_data.xml',
        'data/chat2work_ussd_data.xml',
        'views/chat2work_views.xml',
        'views/chat2work_ussd_views.xml',
    ],
    'application': True,
    'installable': True,
}
