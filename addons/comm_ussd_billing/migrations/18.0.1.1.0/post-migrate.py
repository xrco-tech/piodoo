# -*- coding: utf-8 -*-
"""The shipped South African USSD rate was a placeholder (USD 0.02 a session).
Africa's Talking charges R0.50 for every 20 seconds when the code is free to
the end user. The rate is no-update data, so it is corrected here; a rate
someone has already changed by hand is left alone."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rate = env.ref('comm_ussd_billing.rate_ussd_za_session', raise_if_not_found=False)
    zar = env.ref('base.ZAR', raise_if_not_found=False)
    if not rate or not zar:
        return
    if rate.unit == 'session' and abs(rate.price_usd - 0.02) < 1e-9 and not rate.price_local:
        rate.write({'unit': 'block', 'block_seconds': 20, 'price_usd': 0.0,
                    'price_local': 0.5, 'local_currency_id': zar.id})
        card = rate.card_id
        if card and (card.notes or '').startswith('Placeholder rates'):
            card.notes = ("Africa's Talking charges per 20 seconds of a session: R0.50 when "
                          "the code is free to the end user, R0.25 when the cost is shared.")
