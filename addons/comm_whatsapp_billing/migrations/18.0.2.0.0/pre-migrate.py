# -*- coding: utf-8 -*-
"""Drop the old WhatsApp-specific billing tables before the module loads
against comm_billing_core. Ledger rows were empty in production; rate rows
will be re-seeded from XML."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    obsolete_tables = [
        'whatsapp_billing_event',
        'whatsapp_rate',
        'whatsapp_rate_card',
        'whatsapp_fx_rate',
        'whatsapp_free_window',
    ]
    obsolete_models = [
        'whatsapp.billing.event',
        'whatsapp.rate',
        'whatsapp.rate.card',
        'whatsapp.fx.rate',
        'whatsapp.free.window',
        'whatsapp.cost.simulation',
        'whatsapp.billing.backfill',
    ]

    for t in obsolete_tables:
        cr.execute(f'DROP TABLE IF EXISTS {t} CASCADE')
        _logger.info('Dropped legacy table %s', t)

    if obsolete_models:
        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'comm_whatsapp_billing' "
            "AND model = ANY(%s)", (obsolete_models,))
        cr.execute(
            "DELETE FROM ir_model_fields WHERE model = ANY(%s)",
            (obsolete_models,))
        cr.execute(
            "DELETE FROM ir_model WHERE model = ANY(%s)",
            (obsolete_models,))
        _logger.info('Purged legacy model references')
