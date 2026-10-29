# -*- coding: utf-8 -*-
"""Blank out ID numbers already stored in plain text in inbound WhatsApp
messages (sent before redaction existed)."""

from odoo.addons.chat2work.models.chat2work_ussd import ID_LIKE, ID_REDACTED


def migrate(cr, version):
    cr.execute(r"""
        SELECT id, message_body, raw_message_data FROM whatsapp_message
         WHERE is_incoming AND (message_body ~ '\d[\s.-]?\d' OR raw_message_data ~ '\d[\s.-]?\d')
    """)
    for msg_id, body, raw in cr.fetchall():
        new_body = ID_LIKE.sub(ID_REDACTED, body) if body else body
        new_raw = ID_LIKE.sub(ID_REDACTED, raw) if raw else raw
        if (new_body, new_raw) != (body, raw):
            cr.execute("UPDATE whatsapp_message SET message_body = %s, raw_message_data = %s WHERE id = %s",
                       (new_body, new_raw, msg_id))
