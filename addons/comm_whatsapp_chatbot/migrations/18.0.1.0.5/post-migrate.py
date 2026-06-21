# -*- coding: utf-8 -*-
"""Promote per-bot sender_address values into the new account models so each
existing chatbot keeps routing to the right number / sender ID / service code.

Idempotent: if an account with the same identifier already exists we reuse it.
Bots get their whatsapp_account_id / sms_account_id / ussd_account_id set
in the second migration step (in the chatbot field add).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Promote each distinct channel + sender_address pair from existing
    # whatsapp.chatbot rows into a corresponding account record. Reads from
    # the legacy snapshot column the pre-migrate stored, since by the time
    # this runs sender_address is already a computed field.
    cr.execute(
        """
        SELECT DISTINCT channel, sender_address_legacy, name
        FROM whatsapp_chatbot
        WHERE sender_address_legacy IS NOT NULL AND sender_address_legacy <> ''
        """
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info("No bots with sender_address — nothing to promote into accounts")
        return

    seen_wa, seen_sms, seen_ussd = set(), set(), set()
    for channel, sender_address, bot_name in rows:
        if channel == 'whatsapp':
            if sender_address in seen_wa:
                continue
            seen_wa.add(sender_address)
            cr.execute(
                "SELECT id FROM comm_whatsapp_account WHERE phone_number_id = %s",
                (sender_address,),
            )
            if cr.fetchone():
                continue
            cr.execute(
                """
                INSERT INTO comm_whatsapp_account
                    (name, sequence, active, phone_number, phone_number_id,
                     is_default, create_date, write_date)
                VALUES (%s, %s, %s, %s, %s, %s,
                        NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                """,
                (f'WhatsApp — {bot_name}', 10, True, '', sender_address, False),
            )
            _logger.info("Created WhatsApp account for phone_number_id=%s", sender_address)
        elif channel == 'sms':
            if sender_address in seen_sms:
                continue
            seen_sms.add(sender_address)
            cr.execute(
                "SELECT id FROM comm_sms_account WHERE sender_id = %s",
                (sender_address,),
            )
            if cr.fetchone():
                continue
            cr.execute(
                """
                INSERT INTO comm_sms_account
                    (name, sequence, active, provider, sender_id,
                     is_default, create_date, write_date)
                VALUES (%s, %s, %s, %s, %s, %s,
                        NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                """,
                (f'SMS — {bot_name}', 10, True, 'infobip', sender_address, False),
            )
            _logger.info("Created SMS account for sender_id=%s", sender_address)
        elif channel == 'ussd':
            if sender_address in seen_ussd:
                continue
            seen_ussd.add(sender_address)
            cr.execute(
                "SELECT id FROM comm_ussd_account WHERE service_code = %s",
                (sender_address,),
            )
            if cr.fetchone():
                continue
            cr.execute(
                """
                INSERT INTO comm_ussd_account
                    (name, sequence, active, provider, service_code,
                     is_default, create_date, write_date)
                VALUES (%s, %s, %s, %s, %s, %s,
                        NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                """,
                (f'USSD — {bot_name}', 10, True, 'generic', sender_address, False),
            )
            _logger.info("Created USSD account for service_code=%s", sender_address)

    # Wire each bot to its matching account (joining on the legacy snapshot).
    cr.execute(
        """
        UPDATE whatsapp_chatbot c
        SET whatsapp_account_id = a.id
        FROM comm_whatsapp_account a
        WHERE c.channel = 'whatsapp'
          AND c.sender_address_legacy IS NOT NULL
          AND c.sender_address_legacy <> ''
          AND a.phone_number_id = c.sender_address_legacy
        """
    )
    cr.execute(
        """
        UPDATE whatsapp_chatbot c
        SET sms_account_id = a.id
        FROM comm_sms_account a
        WHERE c.channel = 'sms'
          AND c.sender_address_legacy IS NOT NULL
          AND c.sender_address_legacy <> ''
          AND a.sender_id = c.sender_address_legacy
        """
    )
    cr.execute(
        """
        UPDATE whatsapp_chatbot c
        SET ussd_account_id = a.id
        FROM comm_ussd_account a
        WHERE c.channel = 'ussd'
          AND c.sender_address_legacy IS NOT NULL
          AND c.sender_address_legacy <> ''
          AND a.service_code = c.sender_address_legacy
        """
    )
    # Drop the snapshot column — sender_address is now derived from the account.
    cr.execute("ALTER TABLE whatsapp_chatbot DROP COLUMN IF EXISTS sender_address_legacy")
    _logger.info("Wired existing chatbots to their backfilled accounts; dropped legacy column")
