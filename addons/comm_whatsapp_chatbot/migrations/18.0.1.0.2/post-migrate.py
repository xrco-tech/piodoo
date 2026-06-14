# -*- coding: utf-8 -*-
"""Backfill whatsapp.chatbot.contact.chatbot_ids from message history.

Up to this version, contact.chatbot_ids (which records every chatbot a contact
has ever entered) was declared but never written to. We can derive the same
truth retroactively from whatsapp.chatbot.message: any (contact_id, chatbot_id)
pair that has at least one message means the contact has touched that chatbot.

Bulk-insert via raw SQL is dramatically faster than ORM writes on large
message histories. The relation table for the M2M follows Odoo's default
naming: whatsapp_chatbot_contact_whatsapp_chatbot_rel.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Discover the relation table for contact.chatbot_ids (Odoo names it by
    # combining both models alphabetically with a '_rel' suffix).
    cr.execute("""
        SELECT relation FROM ir_model_fields
        WHERE model = 'whatsapp.chatbot.contact' AND name = 'chatbot_ids'
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row or not row[0]:
        _logger.warning("Could not find relation table for contact.chatbot_ids; skipping backfill")
        return
    rel_table = row[0]

    # Insert every distinct (contact, chatbot) pair from message history,
    # skipping pairs that already exist (idempotent re-run).
    cr.execute(f"""
        INSERT INTO {rel_table} (whatsapp_chatbot_contact_id, whatsapp_chatbot_id)
        SELECT DISTINCT m.contact_id, m.chatbot_id
        FROM whatsapp_chatbot_message m
        WHERE m.contact_id IS NOT NULL AND m.chatbot_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    inserted = cr.rowcount

    # Also include contacts whose last_chatbot_id points at a bot — covers
    # the case where the message itself is gone but engagement is still tracked.
    cr.execute(f"""
        INSERT INTO {rel_table} (whatsapp_chatbot_contact_id, whatsapp_chatbot_id)
        SELECT c.id, c.last_chatbot_id
        FROM whatsapp_chatbot_contact c
        WHERE c.last_chatbot_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    inserted += cr.rowcount

    _logger.info(
        "Backfilled whatsapp.chatbot.contact.chatbot_ids: %s new (contact, chatbot) links from history",
        inserted,
    )
