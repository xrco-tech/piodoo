# -*- coding: utf-8 -*-
{
    'name': 'UCX',
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

- Root application menu ("UCX") + the full top-level tab structure
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
    #   Phase 5  Tickets    -> helpdesk (uninstallable on this instance — blocked)
    'depends': [
        'base',
        'base_setup',                # General Settings action (cx_menus)
        'mail',
        'contacts',
        # Phase 1 — Conversations (Gen-2 trunk + channel adapters, all reused):
        'comm_chatbot',
        'comm_chatbot_whatsapp',
        'comm_chatbot_sms',
        'comm_chatbot_web',
        'comm_chatbot_email',        # new adapter, this repo
        'comm_whatsapp',             # WhatsApp account config (referenced by cx_menus)
        'comm_sms',                  # SMS account config (referenced by cx_menus)
        'comm_whatsapp_calling',     # Voice/Calls widget system, reused wholesale
        # Phase 3 — Billing (shared ledger + Meta rate cards + cost simulator):
        'comm_billing_core',
        'comm_whatsapp_billing',
        # Phase 4 — Marketing (omnichannel campaign engine + budget caps):
        'comm_campaign',
        # Second inbox design: surfaces the Contact Centre (Gen-1) inbox as-is
        # AND lets the UCX-native CC-skin inbox reuse its o_cc_inbox_* styles.
        # NOTE: this pulls the Gen-1 Contact Centre app into UCX's dep graph
        # (already installed on this instance).
        'contact_centre_inbox',
    ],
    'data': [
        'security/cx_module_groups.xml',
        'security/ir.model.access.csv',
        'data/cx_webhook_cron.xml',
        'views/cx_conversation_views.xml',
        'views/cx_inbox_views.xml',
        'views/cx_bot_views.xml',
        'views/cx_report_views.xml',
        'views/cx_dashboard_views.xml',
        'views/cx_copilot_views.xml',
        'views/cx_integration_views.xml',
        'views/cx_ai_ops_views.xml',
        'views/cx_queue_views.xml',
        'views/cx_audience_views.xml',
        'views/cx_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cx_module/static/src/inbox/inbox.scss',
            'cx_module/static/src/inbox/inbox.js',
            'cx_module/static/src/inbox/inbox.xml',
            'cx_module/static/src/inbox_cc/inbox_cc.js',
            'cx_module/static/src/inbox_cc/inbox_cc.xml',
            'cx_module/static/src/flow/flow.scss',
            'cx_module/static/src/flow/flow.js',
            'cx_module/static/src/flow/flow.xml',
            'cx_module/static/src/ai_ops/ai_ops.scss',
            'cx_module/static/src/ai_ops/ai_ops.js',
            'cx_module/static/src/ai_ops/ai_ops.xml',
            'cx_module/static/src/dashboard/dashboard.scss',
            'cx_module/static/src/dashboard/dashboard.js',
            'cx_module/static/src/dashboard/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
