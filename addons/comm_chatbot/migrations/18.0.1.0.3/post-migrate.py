# -*- coding: utf-8 -*-
"""The shipped Claude Haiku 4.5 rates were the older $0.80 / $4 per million
tokens. Anthropic charges $1 / $5, cache reads at 0.1x input and cache writes
at 1.25x. The rates are no-update data, so they are corrected here; a rate
someone has already changed by hand is left alone."""
from odoo import SUPERUSER_ID, api

# xml id suffix: (shipped price, correct price), USD per 1,000 tokens
RATES = {
    'input': (0.0008, 0.001),
    'output': (0.004, 0.005),
    'cache_read': (0.00008, 0.0001),
    'cache_write': (0.001, 0.00125),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for suffix, (old, new) in RATES.items():
        rate = env.ref('comm_chatbot.rate_anthropic_haiku_4_5_%s' % suffix,
                       raise_if_not_found=False)
        if rate and abs(rate.price_usd - old) < 1e-9:
            rate.price_usd = new
