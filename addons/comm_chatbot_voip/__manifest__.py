# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — VoIP Channel',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'VoIP Calls as a channel: channel registration, provider account & call log (foundation)',
    'description': """
VoIP Channel (foundation)
=========================
Registers **VoIP Calls** as a comm.channel (Gen-2 trunk) with a stub adapter,
plus a provider-agnostic account (comm.voip.account) and a call log
(comm.voip.call). No live calling yet — this is the channel + config + logging
foundation. A follow-up wires a specific provider (Infobip Voice / SIP / Twilio)
into the adapter's send()/receive().
    """,
    'author': 'XR Co.',
    'website': 'https://github.com/xrco-tech/piodoo',
    'license': 'LGPL-3',
    'depends': ['comm_chatbot', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_channel_data.xml',
        'views/comm_voip_views.xml',
    ],
    'installable': True,
}
