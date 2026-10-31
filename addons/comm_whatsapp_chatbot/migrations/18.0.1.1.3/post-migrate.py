# -*- coding: utf-8 -*-
"""Give each existing USSD account its own webhook token (the column default
fills every existing row with the same value)."""
import logging
import secrets

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT id FROM comm_ussd_account")
    ids = [row[0] for row in cr.fetchall()]
    for account_id in ids:
        cr.execute("UPDATE comm_ussd_account SET webhook_token = %s WHERE id = %s",
                   (secrets.token_urlsafe(24), account_id))
    _logger.info("Generated webhook tokens for %s USSD account(s)", len(ids))
