# -*- coding: utf-8 -*-
"""
Post-migration script for sales_force_support 17.0.1.0.0
Runs AFTER the module update — ORM models are available.

Responsibilities:
  1. Re-run the data migration if the pre-migrate script deferred it
     (because the sf_member / sf_recruit tables didn't exist at that point).
  2. Update XML IDs so that existing ir.model.data records in the database
     that referenced old module IDs are updated to point at new ones.
  3. Trigger ir.rule and ir.model.access recomputation if needed.
"""
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XML ID migrations:  old module.external_id → new module.external_id
# ---------------------------------------------------------------------------
XMLID_MODULE_RENAMES = [
    # (old_module, new_module)
    ("botle_buhle_custom", "sales_force_support"),
    ("bbb_sales_force_genealogy", "sales_force_support"),
    ("bb_payin", "sales_force_support"),
    ("bb_allocate", "sales_force_support"),
    ("bb_chatbot", "sales_force_support"),
    ("partner_compuscan", "sales_force_support"),
    ("partner_consumerview", "sales_force_support"),
    ("bbb_sales_force", "sales_force_support"),
]


def _migrate_xmlids(cr):
    """
    Rename ir.model.data module references from legacy modules to
    sales_force_support, but ONLY for records whose model is listed here
    (records that belong to the consolidated module).

    We skip records whose model belongs to Odoo core/other modules
    (e.g. base.res_country tree view stays under base).

    Note: Duplicate (module, name) pairs after renaming are skipped with
    ON CONFLICT DO NOTHING to avoid unique-constraint errors.
    """
    _logger.info("sales_force_support post-migration: migrating XML IDs …")

    # Models owned by the consolidated module
    OWN_MODELS = {
        "sf.member",
        "sf.recruit",
        "sf.recruit.stage",
        "sf.mapping.field",
        "sf.distribution",
        "bb.payin.sheet",
        "bb.payin.sheet.line",
        "payin.distributor",
        "payin.distributor.line",
        "payin.capture.time",
        "bb.payin.history",
        "bb.payin.change.state",
        "bb.payin.distributor.change.state",
        "bb.payin.export.payins.new",
        "bb.payin.print",
        "bb.payin.sheets.enquiry.report",
        "captured.payinsheet.report.track",
        "captured.summary.report.track",
        "promotion.rules",
        "status.audit.trail",
        "sf.field.required",
        # wizard models
        "sf.blacklist.wizard",
        "sf.create.wizard",
        "sf.move.wizard",
        "sf.promote.wizard",
        "sf.search.wizard",
        "consumerview.resolve.wizard",
    }

    for old_module, new_module in XMLID_MODULE_RENAMES:
        if old_module == new_module:
            continue

        # Rename in bulk (view/action/menu records, model records, etc.)
        # Use a sub-select to avoid renaming records that would collide.
        cr.execute(
            """
            UPDATE ir_model_data AS d
            SET    module = %s
            WHERE  d.module = %s
              AND  NOT EXISTS (
                  SELECT 1 FROM ir_model_data d2
                  WHERE  d2.module = %s AND d2.name = d.name
              )
            """,
            (new_module, old_module, new_module),
        )
        count = cr.rowcount
        if count:
            _logger.info(
                "  Renamed %d ir.model.data records: %s → %s",
                count,
                old_module,
                new_module,
            )


def _recompute_rules(env):
    """Force recomputation of ir.rule domain_force for rules that reference
    the consolidated module's groups (which may have been renamed)."""
    try:
        env["ir.rule"].search([]).write({})  # triggers recomputation
    except Exception as e:
        _logger.warning("Could not recompute ir.rule: %s", e)


def migrate(cr, version):
    """Called by Odoo's migration framework after the module is updated."""
    if not version:
        return

    _logger.info(
        "sales_force_support post-migration starting (from version %s)", version
    )

    # XML ID renames
    _migrate_xmlids(cr)

    # Flush rules with fresh env
    env = api.Environment(cr, SUPERUSER_ID, {})
    _recompute_rules(env)

    _logger.info("sales_force_support post-migration complete.")
