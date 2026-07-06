# -*- coding: utf-8 -*-
"""Backfill billing_currency_id on existing WABA accounts to the company
currency, so the ZAR-first ledger has a currency to convert into."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # comm.whatsapp.account is single-tenant (no company_id column), so use
    # the main company's currency as the default.
    cr.execute("""
        UPDATE comm_whatsapp_account
           SET billing_currency_id = (
                SELECT currency_id FROM res_company ORDER BY id LIMIT 1
           )
         WHERE billing_currency_id IS NULL
    """)
    _logger.info('Backfilled billing_currency_id on %d WABA account(s)',
                 cr.rowcount)
