# -*- coding: utf-8 -*-
"""Snapshot the legacy sender_address values before the schema change turns
the column into a computed field (which would re-compute it to '' for every
existing bot before our post-migration could read it).

We park the values in a sibling column `sender_address_legacy`. The
post-migration reads from there and drops the column when done.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE whatsapp_chatbot
        ADD COLUMN IF NOT EXISTS sender_address_legacy VARCHAR
        """
    )
    cr.execute(
        """
        UPDATE whatsapp_chatbot
        SET sender_address_legacy = sender_address
        WHERE sender_address IS NOT NULL
          AND sender_address <> ''
          AND (sender_address_legacy IS NULL OR sender_address_legacy = '')
        """
    )
    _logger.info("Snapshotted sender_address into sender_address_legacy for %s rows", cr.rowcount)
