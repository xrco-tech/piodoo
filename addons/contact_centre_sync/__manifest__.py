# -*- coding: utf-8 -*-
{
    "name": "Contact Centre Live Sync",
    "version": "18.0.1.0.0",
    "category": "Communications",
    "summary": "Mirrors live WhatsApp messages and calls into the Contact Centre unified inbox",
    "description": """
Glue module linking comm_whatsapp and comm_whatsapp_calling to contact_centre.
Neither parent module depends on or knows about this one, following the same
auto-install pattern as comm_whatsapp_calling_chatbot.
""",
    "author": "Tsela NavTech",
    "license": "LGPL-3",
    "depends": ["contact_centre", "comm_whatsapp", "comm_whatsapp_calling", "mail"],
    "data": ["views/contact_centre_contact_views.xml"],
    "installable": True,
    "auto_install": True,
    "application": False,
}
