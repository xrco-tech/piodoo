# -*- coding: utf-8 -*-
{
    'name': 'Communication Campaigns',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Omni-channel campaign engine on top of comm_chatbot + billing',
    'description': """
Marketing / campaign layer that treats every send as a bot invocation:

- Static / dynamic / streaming audience resolution
- Channel-fallback resolver: try WA → SMS → email based on partner reachability
- Quiet hours per channel (POPIA-safe), timezone-aware
- Global + per-channel + per-campaign opt-out
- Soft budget enforcement with 80/100% notifications, hard-stop opt-in
- A/B variants with deterministic partner assignment
- Attribution: any conversation opened within the attribution window
  attributes the campaign's cost and outcome
- Rate limiting: campaign-throttle + channel-throttle + global-throttle
- Retry policy per failure class
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_chatbot',
        'comm_billing_core',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/comm_campaign_views.xml',
        'views/comm_campaign_send_views.xml',
        'views/comm_partner_pref_views.xml',
        'views/comm_campaign_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
