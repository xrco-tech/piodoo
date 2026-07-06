# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Billing',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Predict, track and simulate Meta WhatsApp Business Platform costs',
    'description': """
WhatsApp Billing
================

Real-time cost tracking and prediction for WhatsApp Business Platform usage
built on top of comm_whatsapp (and, when installed, comm_whatsapp_calling).

- Versioned rate cards: Jul 2025 per-message, Aug 2026 hybrid (MBA tokens),
  Oct 2026 paid-service — switchable by effective date.
- Unit-agnostic ledger: messages, call minutes, MBA tokens.
- 24h customer-service and 72h entry-point free-window handling.
- Campaign cost simulator with side-by-side rate-card comparison.
- Backfill wizard: replay last N months of history into the ledger.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_whatsapp',
        'comm_whatsapp_calling',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/whatsapp_rate_card_data.xml',
        'data/whatsapp_rate_za_data.xml',
        'views/whatsapp_rate_card_views.xml',
        'views/whatsapp_rate_views.xml',
        'views/whatsapp_billing_event_views.xml',
        'views/whatsapp_free_window_views.xml',
        'views/whatsapp_fx_rate_views.xml',
        'views/comm_whatsapp_account_views.xml',
        'wizards/whatsapp_cost_simulation_views.xml',
        'wizards/whatsapp_billing_backfill_views.xml',
        'views/whatsapp_billing_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
