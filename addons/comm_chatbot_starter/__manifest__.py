# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — Starter Pack',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Sample bots for smoke-testing comm_chatbot end-to-end',
    'description': """
Ships a "hello world" canary bot that responds to the keyword `canary_hello`
on WhatsApp. Installed in shadow mode by default — flip engine_mode to
`live` on the bot to make it actually send.

Useful for:
- Confirming inbound routing works
- Verifying the renderer produces the right payload per channel
- Watching the executor advance through steps
- Sanity-checking billing event creation
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_chatbot',
        'comm_chatbot_whatsapp',
    ],
    'data': [
        'data/canary_bot_data.xml',
    ],
    'installable': True,
    'auto_install': False,
}
