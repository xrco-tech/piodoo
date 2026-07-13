# -*- coding: utf-8 -*-
{
    "name": "Contact Centre Inbox",
    "version": "18.0.1.0.0",
    "category": "Communications",
    "summary": "Unified 3-pane inbox: conversation list, thread, AI copilot + internal notes",
    "description": """
Custom OWL client action giving agents a single screen to work conversations
from: a conversation list, the actual WhatsApp/SMS/voice thread with a
composer to reply, and a side panel with the AI copilot (if
contact_centre_ai_copilot is installed) plus internal notes (the
contact.centre.contact chatter added by contact_centre_sync). Updates in
real time via bus.bus.
""",
    "author": "Tsela NavTech",
    "license": "LGPL-3",
    "depends": ["contact_centre", "comm_whatsapp_calling"],
    "data": [
        "views/contact_centre_inbox_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "contact_centre_inbox/static/src/inbox/inbox.xml",
            "contact_centre_inbox/static/src/inbox/inbox.js",
            "contact_centre_inbox/static/src/inbox/voice_script_panel.js",
            "contact_centre_inbox/static/src/inbox/inbox.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
