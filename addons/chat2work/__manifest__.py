# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'Job openings, interview slots and bookings for the Chat2Work service',
    'description': """
Chat2Work
=========
Minimal recruitment data behind the Chat2Work omnichannel service (USSD /
WhatsApp / SMS): job openings, bookable interview slots, and the interview
bookings candidates make. The USSD chatbot reads these live so the menus are
dynamic.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'contacts', 'sms'],
    'data': [
        'security/ir.model.access.csv',
        'data/chat2work_data.xml',
        'views/chat2work_views.xml',
    ],
    'application': True,
    'installable': True,
}
