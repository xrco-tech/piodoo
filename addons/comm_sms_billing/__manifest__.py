# -*- coding: utf-8 -*-
{
    'name': 'SMS Billing',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'SMS channel adapter for comm_billing_core (Infobip)',
    'description': """
SMS Billing
===========

Hooks the sms.sms model into the shared comm.billing.event ledger.
Segment-based pricing (160 GSM-7 / 70 UCS-2), country + direction resolution.
Seeds placeholder ZA rates that you'll refresh from Infobip's monthly bill.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_billing_core',
        'comm_sms',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_billing_sms_rate_cards.xml',
        'data/comm_billing_sms_za_rates.xml',
    ],
    'installable': True,
    'auto_install': False,
}
