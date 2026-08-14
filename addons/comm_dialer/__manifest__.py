# -*- coding: utf-8 -*-
{
    'name': 'Comm Dialer — Progressive / Predictive',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Outbound dialer: campaigns, call lists, agent pacing (preview / progressive / predictive)',
    'description': """
Outbound Dialer
===============

Adds progressive and predictive outbound dialling on top of the VoIP channel
(comm_chatbot_voip). The provider actually placing/bridging calls is wired in a
follow-up per-provider module (Africa's Talking Voice / Infobip / Asterisk ARI);
this layer models everything above the telephony:

- **comm.dialer.campaign** — mode (preview/progressive/predictive), caller-ID
  (a comm.voip.account), calling window, retry policy, pacing ratio + abandon
  governor, live stats.
- **comm.dialer.contact** — the call-list rows with per-contact state machine,
  attempts, retry scheduling and last disposition.
- **comm.dialer.agent.session** — agent presence (offline/ready/on_call/wrap/
  paused) that the pacer reads to decide how many lines to open.
- **comm.dialer.dnc** — Do-Not-Call list (POPIA / CPA), checked before every dial.

Pacing runs from a cron (**disabled by default** — enable it once a real
provider is wired into comm.voip.account.originate/bridge).
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': [
        'comm_chatbot_voip',      # voip channel + account + call log
        'comm_whatsapp_calling',  # comm.disposition (outcome codes)
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_dialer_data.xml',
        'views/comm_dialer_campaign_views.xml',
        'views/comm_dialer_contact_views.xml',
        'views/comm_dialer_agent_views.xml',
        'views/comm_dialer_dnc_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Vendored JsSIP (plain UMD, sets window.JsSIP) — must load first.
            'comm_dialer/static/src/lib/jssip.min.js',
            'comm_dialer/static/src/softphone/softphone.scss',
            'comm_dialer/static/src/softphone/softphone.js',
            'comm_dialer/static/src/softphone/softphone.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

