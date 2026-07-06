# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Billing',
    'version': '18.0.2.0.0',
    'category': 'Communications',
    'summary': 'WhatsApp channel adapter for comm_billing_core',
    'description': """
WhatsApp Billing
================

Channel adapter that hooks WhatsApp messages and calls into the shared
comm_billing_core ledger:

- Seeds Meta rate cards: Jul 2025 per-message, Aug 2026 hybrid (MBA tokens),
  Oct 2026 paid-service.
- Hooks whatsapp.message and whatsapp.call.log write() to create
  comm.billing.event rows automatically from Meta's status webhooks.
- Adds billing currency + fallback FX to comm.whatsapp.account.
- Backfill wizard replays historical messages/calls into the ledger.
- Cost simulator projects campaigns against multiple rate cards.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_billing_core',
        'comm_whatsapp',
        'comm_whatsapp_calling',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_billing_whatsapp_rate_cards.xml',
        'data/comm_billing_whatsapp_za_rates.xml',
        'views/comm_whatsapp_account_views.xml',
        'wizards/whatsapp_cost_simulation_views.xml',
        'wizards/whatsapp_billing_backfill_views.xml',
        'views/whatsapp_billing_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
