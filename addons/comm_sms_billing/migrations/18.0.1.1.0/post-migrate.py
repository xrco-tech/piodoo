# -*- coding: utf-8 -*-
"""Correct the Infobip ZA domestic outbound rate.

The rates are noupdate data, so the XML change doesn't reach existing
databases. Only the untouched placeholder (USD 0.008) is replaced; a rate
someone already edited is left alone.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE comm_billing_rate r
           SET price_usd = 0.1012
          FROM ir_model_data d
         WHERE d.module = 'comm_sms_billing'
           AND d.name = 'rate_sms_za_outbound_domestic'
           AND d.model = 'comm.billing.rate'
           AND r.id = d.res_id
           AND r.price_usd = 0.008
        """
    )
    _logger.info("Infobip ZA domestic outbound rate corrected on %s row(s)", cr.rowcount)
