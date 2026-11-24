# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — USSD Adapter',
    'version': '18.0.1.1.2',
    'category': 'Communications',
    'summary': 'USSD channel adapter for comm_chatbot: a USSD code can run a flow',
    'description': """
A USSD code can run a flow of the channel-agnostic bot engine.

- A USSD account (one dialled code) can be connected to a flow. Sessions on
  that code then run the flow, through whichever gateway answers the code.
  An account that is not connected behaves exactly as before.
- Each dial is its own conversation, one screen a turn, and is closed when
  the caller or the network ends it.
- Sessions are recorded and charged like other USSD sessions.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': ['comm_chatbot', 'comm_whatsapp_chatbot'],
    'data': ['security/ir.model.access.csv'],
    'installable': True,
    'auto_install': False,
}
