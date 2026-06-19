# -*- coding: utf-8 -*-
"""Backfill whatsapp.chatbot.channel before the registry enforces NOT NULL.

The `channel` field is required, so existing rows (which predate the column)
need a value before the ALTER TABLE / CHECK constraint runs. Default every
existing row to 'whatsapp' — the bots created so far were all WhatsApp bots.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Add the column if it doesn't exist yet (older Odoo versions create it later).
    cr.execute("""
        ALTER TABLE whatsapp_chatbot
        ADD COLUMN IF NOT EXISTS channel VARCHAR
    """)
    cr.execute("""
        UPDATE whatsapp_chatbot
        SET channel = 'whatsapp'
        WHERE channel IS NULL
    """)
    _logger.info("Backfilled whatsapp.chatbot.channel='whatsapp' for %s existing rows", cr.rowcount)
