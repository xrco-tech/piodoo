# -*- coding: utf-8 -*-

def migrate(cr, version):
    """
    Add partial unique index so only one incoming chatbot message per
    WhatsApp message can exist. Prevents double-send when webhook is delivered twice.
    """
    cr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_chatbot_message_incoming_wa_message_uniq
        ON whatsapp_chatbot_message (wa_message_id)
        WHERE type = 'incoming' AND wa_message_id IS NOT NULL;
    """)

