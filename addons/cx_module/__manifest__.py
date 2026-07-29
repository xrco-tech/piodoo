# -*- coding: utf-8 -*-
{
    'name': 'Unified CX',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'One workspace to manage a customer end-to-end across every channel',
    'description': """
Unified Customer Experience (UCX)
=================================

A single Odoo app that gives support, contact-centre, sales, and marketing
agents one workspace to manage a customer end-to-end — one inbox across
WhatsApp / SMS / web chat / voice / email, one billing ledger across every
channel, one campaign engine, and one customer timeline.

This is **Phase 0**: the standalone module shell.

- Root application menu ("Unified CX") + the full top-level tab structure
  (Workspace / Conversations / Tickets / Sales / Marketing / Customers /
  Reporting / Billing / Configuration) from the Menu Structure spec.
- Security groups cx.group_cx_agent < cx.group_cx_manager < cx.group_cx_admin
  with the implied_ids hierarchy that later phases gate menus against.

Later phases add the feature dependencies (comm_chatbot, comm_billing_core,
comm_campaign, the channel adapters, helpdesk, ...) and wire the real actions
behind each menu item. Phase 0 deliberately depends on nothing beyond base
Odoo so the shell installs clean on its own.
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    # Deps grow per phase:
    #   Phase 4  Marketing  -> comm_campaign
    #   Phase 5  Tickets    -> helpdesk (uninstallable on this instance — blocked)
    'depends': [
        'base',
        'mail',
        'contacts',
        # Phase 1 — Conversations (Gen-2 trunk + channel adapters, all reused):
        'comm_chatbot',
        'comm_chatbot_whatsapp',
        'comm_chatbot_sms',
        'comm_chatbot_web',
        'comm_chatbot_email',        # new adapter, this repo
        'comm_whatsapp_calling',     # Voice/Calls widget system, reused wholesale
        # Phase 3 — Billing (shared ledger + Meta rate cards + cost simulator):
        'comm_billing_core',
        'comm_whatsapp_billing',
    ],
    'data': [
        'security/cx_module_groups.xml',
        'security/ir.model.access.csv',
        'views/cx_conversation_views.xml',
        'views/cx_inbox_views.xml',
        'views/cx_bot_views.xml',
        'views/cx_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cx_module/static/src/inbox/inbox.scss',
            'cx_module/static/src/inbox/inbox.js',
            'cx_module/static/src/inbox/inbox.xml',
            'cx_module/static/src/flow/flow.scss',
            'cx_module/static/src/flow/flow.js',
            'cx_module/static/src/flow/flow.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
