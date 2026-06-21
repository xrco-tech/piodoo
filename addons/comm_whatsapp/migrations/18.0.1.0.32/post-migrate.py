# -*- coding: utf-8 -*-
"""Promote the existing single-account ir.config_parameter values into a
'Default WhatsApp' account so existing single-account installs keep working
without manual intervention.

Idempotent: only creates the row when none exists. Safe to re-run.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT COUNT(*) FROM comm_whatsapp_account")
    if cr.fetchone()[0] > 0:
        _logger.info("comm.whatsapp.account already populated; skipping backfill")
        return

    keys = (
        'comm_whatsapp.phone_number_id',
        'comm_whatsapp.business_account_id',
        'comm_whatsapp.access_token',
        'comm_whatsapp.long_lived_token',
        'comm_whatsapp.app_secret',
        'comm_whatsapp.webhook_verify_token',
    )
    cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key = ANY(%s)",
        (list(keys),),
    )
    params = {row[0]: row[1] for row in cr.fetchall()}

    phone_number_id = params.get('comm_whatsapp.phone_number_id') or ''
    if not phone_number_id:
        _logger.info("No comm_whatsapp.phone_number_id configured; skipping default account backfill")
        return

    # Prefer the long-lived token if present (matches the existing send code's
    # behaviour of treating it as the canonical credential).
    access_token = params.get('comm_whatsapp.long_lived_token') \
        or params.get('comm_whatsapp.access_token') \
        or ''

    cr.execute(
        """
        INSERT INTO comm_whatsapp_account
            (name, sequence, active, phone_number, phone_number_id,
             business_account_id, access_token, app_secret,
             webhook_verify_token, is_default, create_date, write_date)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, %s, %s,
             %s, %s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
        RETURNING id
        """,
        (
            'Default WhatsApp', 10, True,
            '',  # phone_number was never stored globally — admin can fill it in
            phone_number_id,
            params.get('comm_whatsapp.business_account_id') or '',
            access_token,
            params.get('comm_whatsapp.app_secret') or '',
            params.get('comm_whatsapp.webhook_verify_token') or '',
            True,
        ),
    )
    new_id = cr.fetchone()[0]
    _logger.info(
        "Created default WhatsApp account #%s from existing ir.config_parameter values",
        new_id,
    )
