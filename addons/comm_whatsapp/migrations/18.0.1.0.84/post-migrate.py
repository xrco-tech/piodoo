# -*- coding: utf-8 -*-
"""Messages where a person tapped a button or a menu row used to be stored as
"Interactive: button_reply". Rewrite them to say what was chosen, from the
copy of Meta's data kept on the message."""

import json
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Message = env['whatsapp.message']
    cr.execute("""
        SELECT id, message_body, interactive_data FROM whatsapp_message
         WHERE message_type = 'interactive' AND message_body LIKE 'Interactive: %%' AND interactive_data IS NOT NULL
    """)
    changed = 0
    for message_id, body, data in cr.fetchall():
        try:
            interactive = json.loads(data)
        except ValueError:
            continue
        summary = Message._reply_summary({'type': 'interactive', 'interactive': interactive})
        if summary != body:
            cr.execute("UPDATE whatsapp_message SET message_body = %s WHERE id = %s", [summary, message_id])
            changed += 1
    _logger.info("comm_whatsapp: %s tapped replies now say what was chosen", changed)
