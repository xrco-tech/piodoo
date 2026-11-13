# -*- coding: utf-8 -*-
{
    'name': 'USSD Billing',
    'version': '18.0.1.1.0',
    'category': 'Communications',
    'summary': 'USSD channel adapter for comm_billing_core',
    'description': """
Hooks whatsapp.chatbot.ussd.session into the shared comm.billing.event
ledger. Session-based pricing, provider-aware (Africa's Talking, Connect Mobile per 20 s).
Fires when a session's outcome transitions off 'open'.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_billing_core',
        'comm_whatsapp_chatbot',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_billing_ussd_rate_cards.xml',
        'data/comm_billing_ussd_za_rates.xml',
        'data/comm_billing_ussd_connect_mobile.xml',
    ],
    'installable': True,
    'auto_install': False,
}
