# -*- coding: utf-8 -*-
{
    "name": "WhatsApp Calling ↔ Chatbot Glue",
    "version": "18.0.1.0.0",
    "category": "Communications",
    "summary": (
        "Links whatsapp.call.log to whatsapp.chatbot so voice-channel "
        "chatbots can surface a per-chatbot call history. Auto-installs "
        "when both parent modules are present."
    ),
    "author": "If I Could Code (Org)",
    "license": "LGPL-3",
    "depends": [
        "comm_whatsapp_calling",
        "comm_whatsapp_chatbot",
    ],
    "data": [
        "views/whatsapp_chatbot_views.xml",
    ],
    "installable": True,
    "auto_install": True,
    "application": False,
}
