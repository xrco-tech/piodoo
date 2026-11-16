# -*- coding: utf-8 -*-
{
    'name': 'Communication Billing Core',
    'version': '18.0.2.3.0',
    'category': 'Communications',
    'summary': 'Shared rate cards, FX and event ledger for all comm channels',
    'description': """
Communication Billing Core
==========================

Provides the shared plumbing that channel-specific billing modules
(WhatsApp, SMS, USSD, voice) build on top of:

- Versioned rate cards with `billing_model` selector
- Unit-agnostic event ledger (message / segment / session / minute / kilotoken)
- Rate resolver keyed on (channel, country, category, carrier, direction, volume tier)
- USD-based rates + tri-tier FX resolution (provider monthly override →
  Odoo res.currency.rate → account fallback)
- 24h customer-service and 72h entry-point free-window handling
- Reports screen: spend overview, monthly budget with warnings, and a
  monthly statement checked against the providers' invoices
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
    ],
    'data': [
        'security/comm_billing_groups.xml',
        'security/ir.model.access.csv',
        'views/comm_billing_rate_card_views.xml',
        'views/comm_billing_rate_views.xml',
        'views/comm_billing_event_views.xml',
        'views/comm_billing_fx_rate_views.xml',
        'views/comm_billing_free_window_views.xml',
        'views/comm_billing_budget_views.xml',
        'views/comm_billing_menus.xml',
        'report/statement_report.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_billing_core/static/src/reports/reports.scss',
            'comm_billing_core/static/src/reports/reports.js',
            'comm_billing_core/static/src/reports/reports.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
