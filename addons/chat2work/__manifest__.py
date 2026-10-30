# -*- coding: utf-8 -*-
{
    'name': 'Chat2Work',
    'version': '18.0.1.7.0',
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
callback) runs on any USSD account whose Flow Engine is set to Chat2Work. The
same flow runs on WhatsApp (buttons and lists), started by "Hi Chat2Work".

Every new profile gets a personal CV link (/cv/<token>) to upload a CV, build
a standard PDF CV with a guided form, or ask an agent for help. USSD sign-ups
receive it by WhatsApp template or SMS, with SMS as the fallback.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail', 'contacts', 'sms', 'comm_whatsapp', 'comm_whatsapp_chatbot'],
    'data': [
        'security/ir.model.access.csv',
        'data/chat2work_data.xml',
        'data/chat2work_ussd_data.xml',
        'data/chat2work_cv_data.xml',
        'views/chat2work_cv_templates.xml',
        'views/chat2work_views.xml',
        'views/chat2work_ussd_views.xml',
        'wizards/chat2work_ussd_simulator_views.xml',
    ],
    'application': True,
    'installable': True,
}
