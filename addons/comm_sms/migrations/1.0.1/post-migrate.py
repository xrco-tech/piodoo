# -*- coding: utf-8 -*-
"""Backfill the 'Default SMS' account from existing infobip.* config keys."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT COUNT(*) FROM comm_sms_account")
    if cr.fetchone()[0] > 0:
        _logger.info("comm.sms.account already populated; skipping backfill")
        return

    keys = (
        'sms.use_infobip_api',
        'infobip.base_url',
        'infobip.api_key',
        'infobip.default_from_number',
        'infobip.retention_period',
    )
    cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key = ANY(%s)",
        (list(keys),),
    )
    params = {row[0]: row[1] for row in cr.fetchall()}

    sender_id = params.get('infobip.default_from_number') or ''
    if not sender_id:
        _logger.info("No infobip.default_from_number configured; skipping default SMS account backfill")
        return

    try:
        retention = int(params.get('infobip.retention_period') or '1')
    except (TypeError, ValueError):
        retention = 1

    cr.execute(
        """
        INSERT INTO comm_sms_account
            (name, sequence, active, provider, sender_id,
             base_url, api_key, retention_period,
             is_default, create_date, write_date)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, %s, %s,
             %s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
        RETURNING id
        """,
        (
            'Default SMS', 10, True, 'infobip', sender_id,
            params.get('infobip.base_url') or '',
            params.get('infobip.api_key') or '',
            retention,
            True,
        ),
    )
    new_id = cr.fetchone()[0]
    _logger.info(
        "Created default SMS account #%s from existing ir.config_parameter values",
        new_id,
    )
