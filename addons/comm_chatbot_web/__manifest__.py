# -*- coding: utf-8 -*-
{
    'name': 'Comm Chatbot — Web Channel',
    'version': '18.0.1.0.0',
    'category': 'Communications',
    'summary': 'Embeddable web chat widget as a channel adapter for comm_chatbot',
    'description': """
Web channel for comm_chatbot. Enables running any comm.bot on:

- Your Odoo site (drop the widget on any page)
- Third-party websites (embed via <script> tag)
- The device simulator in the bot flow viewer (iPhone / Pixel / iPad / Desktop)

Rich capabilities matching WhatsApp: quick-reply buttons, list menus,
images / video / audio / documents, HTML rendering.
    """,
    'author': 'XR Co.',
    'license': 'LGPL-3',
    'depends': [
        'comm_chatbot',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/comm_channel_data.xml',
        'wizards/comm_bot_web_embed_wizard_views.xml',
        'views/comm_bot_views.xml',
        'views/comm_bot_web_session_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'comm_chatbot_web/static/src/device_sim/device_sim.css',
            'comm_chatbot_web/static/src/device_sim/device_sim_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
