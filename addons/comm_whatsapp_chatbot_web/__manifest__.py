# -*- coding: utf-8 -*-
{
    'name': 'WhatsApp Chatbot — Web Channel',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Embeddable web widget + device simulator for whatsapp.chatbot bots',
    'description': """
Mirrors comm_chatbot_web for the legacy comm_whatsapp_chatbot engine:
- Embeddable chat widget on the site or any external website
- Device simulator inside the WA chatbot flow editor
- Per-bot embed-domain allowlist
- 'Copy embed code' wizard on the chatbot form

Reuses the widget.js and CSS from comm_chatbot_web with a different
endpoint prefix; the backend endpoints here wrap whatsapp.chatbot's
existing /chatbot/simulate/* logic in a token-based web session.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_whatsapp_chatbot',
        'comm_chatbot_web',   # for the shared widget.js/css
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizards/whatsapp_chatbot_web_embed_wizard_views.xml',
        'views/whatsapp_chatbot_views.xml',
        'views/whatsapp_chatbot_web_session_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_whatsapp_chatbot_web/static/src/device_sim/wa_device_sim.js',
            'comm_whatsapp_chatbot_web/static/src/device_sim/wa_device_sim.xml',
            'comm_whatsapp_chatbot_web/static/src/device_sim/wa_device_sim.css',
        ],
    },
    'installable': True,
    'auto_install': False,
}
