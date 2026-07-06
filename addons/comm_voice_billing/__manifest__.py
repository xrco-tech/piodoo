# -*- coding: utf-8 -*-
{
    'name': 'Voice Billing (non-WA)',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Voice channel adapter for comm_billing_core',
    'description': """
Hooks comm.voice.call.session into the shared comm.billing.event ledger.
Minute-based pricing, provider-agnostic (SIP trunk, cloud PBX, etc.).
Fires when a session's ended_at gets set or outcome transitions off 'open'.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_billing_core',
        'comm_whatsapp_chatbot',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_billing_voice_rate_cards.xml',
        'data/comm_billing_voice_za_rates.xml',
    ],
    'installable': True,
    'auto_install': False,
}
