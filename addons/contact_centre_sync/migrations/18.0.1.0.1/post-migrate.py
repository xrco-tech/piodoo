# -*- coding: utf-8 -*-
"""The inbox keeps its own copy of each WhatsApp message's text. Refresh the
copies that still read "Interactive: button_reply" now that the WhatsApp
message says what was chosen (comm_whatsapp 18.0.1.0.84)."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE contact_centre_message m
           SET body_text = w.message_body
          FROM whatsapp_message w
         WHERE w.id = m.whatsapp_message_id
           AND m.body_text LIKE 'Interactive: %%'
           AND w.message_body IS NOT NULL
           AND w.message_body <> m.body_text
    """)
    _logger.info("contact_centre_sync: %s inbox messages now say what was chosen", cr.rowcount)
