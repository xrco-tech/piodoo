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


def _safe_ident(name):
    """Defensive: ensure the identifier from ir_model_fields is a plain
    snake_case name before splicing it into raw SQL."""
    import re
    if not name or not re.match(r'^[a-z_][a-z0-9_]*$', name):
        raise ValueError(f"unexpected identifier from ir_model_fields: {name!r}")
    return name


def migrate(cr, version):
    # ir_model_fields stores the M2M relation TABLE in relation_table and the
    # two foreign-key columns in column1 / column2. `relation` would be the
    # model name (whatsapp.chatbot), which is not what we want here.
    cr.execute("""
        SELECT relation_table, column1, column2 FROM ir_model_fields
        WHERE model = 'whatsapp.chatbot.contact' AND name = 'chatbot_ids'
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row or not row[0]:
        _logger.warning("Could not find relation_table for contact.chatbot_ids; skipping backfill")
        return
    rel_table, contact_col, chatbot_col = (_safe_ident(x) for x in row)

    # Sanity check: the table must exist (Odoo creates it for declared M2Ms at
    # install/upgrade time).
    cr.execute("SELECT to_regclass(%s)", (rel_table,))
    if not cr.fetchone()[0]:
        _logger.warning("Relation table %s does not exist; skipping backfill", rel_table)
        return

    # Backfill from message history: any (contact, chatbot) that ever exchanged
    # a message is a contact who has "entered" that chatbot. ON CONFLICT DO
    # NOTHING makes this safe to re-run.
    cr.execute(f"""
        INSERT INTO {rel_table} ({contact_col}, {chatbot_col})
        SELECT DISTINCT m.contact_id, m.chatbot_id
        FROM whatsapp_chatbot_message m
        WHERE m.contact_id IS NOT NULL AND m.chatbot_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    inserted = cr.rowcount

    # Also include any contact whose last_chatbot_id is set but somehow lacks
    # message history (engagement preserved even when messages were purged).
    cr.execute(f"""
        INSERT INTO {rel_table} ({contact_col}, {chatbot_col})
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
