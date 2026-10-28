# -*- coding: utf-8 -*-
"""Give every existing SMS account its own webhook token.

The column's default is filled once for all existing rows, so without this
they would share a single token.
"""

import logging
import secrets

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT id FROM comm_sms_account")
    ids = [row[0] for row in cr.fetchall()]
    for account_id in ids:
        cr.execute(
            "UPDATE comm_sms_account SET webhook_token = %s WHERE id = %s",
            (secrets.token_urlsafe(24), account_id),
        )
    _logger.info("Generated webhook tokens for %s SMS account(s)", len(ids))
