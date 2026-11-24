# -*- coding: utf-8 -*-
{
    'name': 'Sediba Flows: bring over older bots',
    'version': '18.0.1.0.6',
    'category': 'Communications',
    'summary': 'Copy a bot from the older WhatsApp chatbot into Sediba Flows as a draft',
    'description': """
Sediba Flows: bring over older bots
===================================
Installed by itself when both Sediba Flows and the older WhatsApp chatbot
(comm_whatsapp_chatbot) are present.

Sediba Flows lists the older bots under its flows. "Bring over" copies one
into Sediba Flows as a draft: its steps, choices, variables, keywords and the
bots it jumps to. The older bot is not changed and keeps running. Whatever
could not be carried over is listed on the new flow, so nothing is dropped
without saying so.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['sediba_flows', 'comm_whatsapp_chatbot'],
    'data': [],
    'auto_install': True,
    'installable': True,
}
