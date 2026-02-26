# -*- coding: utf-8 -*-
"""
Pre-migration script for sales_force_support 17.0.1.0.0
Runs BEFORE the module update, so the new tables/models may not exist yet.

Responsibilities:
  1. Copy ir.config_parameter values from legacy module namespaces to
     the new sales_force_support.* namespace.
  2. Migrate hr.employee (sales force only) records to sf.member records.
  3. Migrate hr.applicant records to sf.recruit records.
  4. Update Foreign-Key references in dependent models that point at
     hr.employee / hr.applicant to point at the new tables instead.

Note: Step 2 & 3 run at the SQL level where possible (before ORM is available)
to avoid depending on models that may not exist yet.
"""
import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1.  Config-parameter key mappings
# ---------------------------------------------------------------------------
# Map: (old_key, new_key)
CONFIG_PARAM_MIGRATIONS = [
    # bbb_sales_force_genealogy  →  sales_force_support
    (
        "bbb_sales_force_genealogy.enable_outbound_synchronisation",
        "sales_force_support.enable_outbound_synchronisation",
    ),
    (
        "bbb_sales_force_genealogy.enable_inbound_synchronisation",
        "sales_force_support.enable_inbound_synchronisation",
    ),
    (
        "bbb_sales_force_genealogy.outbound_url",
        "sales_force_support.outbound_url",
    ),
    (
        "bbb_sales_force_genealogy.outbound_database",
        "sales_force_support.outbound_database",
    ),
    (
        "bbb_sales_force_genealogy.outbound_login",
        "sales_force_support.outbound_login",
    ),
    (
        "bbb_sales_force_genealogy.outbound_password",
        "sales_force_support.outbound_password",
    ),
    # botle_buhle_custom  →  sales_force_support
    (
        "botle_buhle_custom.whatsapp_bbbot_sender_token",
        "sales_force_support.whatsapp_bbbot_sender_token",
    ),
    (
        "botle_buhle_custom.whatsapp_bbbot_sender_namespace",
        "sales_force_support.whatsapp_bbbot_sender_namespace",
    ),
    (
        "botle_buhle_custom.whatsapp_bbbot_sender_phone_number_id",
        "sales_force_support.whatsapp_bbbot_sender_phone_number_id",
    ),
    # bb_payin  →  sales_force_support
    ("bb_payin.report_print_count", "sales_force_support.report_print_count"),
    ("bb_payin.voip_access_group_ids", "sales_force_support.voip_access_group_ids"),
    (
        "bb_payin.payin_active_status_reference_date",
        "sales_force_support.payin_active_status_reference_date",
    ),
    ("bb_payin.telviva_username", "sales_force_support.telviva_username"),
    ("bb_payin.telviva_password", "sales_force_support.telviva_password"),
    ("bb_payin.telviva_start_time", "sales_force_support.telviva_start_time"),
    ("bb_payin.telviva_end_time", "sales_force_support.telviva_end_time"),
    ("bb_payin.telviva_duration_min", "sales_force_support.telviva_duration_min"),
    ("bb_payin.telviva_duration_max", "sales_force_support.telviva_duration_max"),
    ("bb_payin.telviva_recordgroup", "sales_force_support.telviva_recordgroup"),
]


def _migrate_config_params(cr):
    """Copy ir.config_parameter values from old keys to new keys.
    Only copies if the old key exists AND the new key doesn't already exist.
    """
    _logger.info("sales_force_support migration: copying config parameters …")
    for old_key, new_key in CONFIG_PARAM_MIGRATIONS:
        cr.execute(
            """
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid,
                                              create_date, write_date)
            SELECT %s, value, create_uid, write_uid, create_date, write_date
            FROM   ir_config_parameter
            WHERE  key = %s
            ON CONFLICT (key) DO NOTHING
            """,
            (new_key, old_key),
        )
        if cr.rowcount:
            _logger.info("  Copied config param: %s → %s", old_key, new_key)


# ---------------------------------------------------------------------------
# 2.  hr.employee  →  sf.member  migration
# ---------------------------------------------------------------------------
def _migrate_sf_members(cr):
    """
    Migrate sales-force hr.employee records to sf.member.

    sf.member uses _inherits={'res.partner': 'partner_id'}, so each member
    needs a res.partner record.  We check whether the employee already has
    an address_home_id pointing to a partner, and reuse it; otherwise we
    create a new res.partner first.

    Only employees with employee_type = 'sales_force' are migrated.
    """
    # Check if sf_member table already has rows — skip if re-running.
    cr.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'sf_member'")
    if not cr.fetchone()[0]:
        _logger.info(
            "sales_force_support migration: sf_member table not yet created, "
            "skipping hr.employee → sf.member data migration (will run post-migrate)"
        )
        return

    cr.execute("SELECT COUNT(*) FROM sf_member")
    if cr.fetchone()[0] > 0:
        _logger.info(
            "sales_force_support migration: sf_member already has records, "
            "skipping hr.employee → sf.member migration"
        )
        return

    # Check that hr_employee table exists
    cr.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'hr_employee'"
    )
    if not cr.fetchone()[0]:
        _logger.info(
            "sales_force_support migration: hr_employee table does not exist, "
            "skipping hr.employee migration"
        )
        return

    _logger.info(
        "sales_force_support migration: migrating hr.employee → sf.member …"
    )

    # Retrieve sales-force hr.employee records.
    # The employee_type field may not exist if bbb_sales_force_genealogy was
    # never installed — guard with a column-existence check.
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'hr_employee' AND column_name = 'employee_type'
        """
    )
    has_employee_type = bool(cr.fetchone())

    if has_employee_type:
        cr.execute(
            """
            SELECT id, name, active, address_home_id, sales_force_code,
                   mobile, mobile_2, street, suburb, city, zip,
                   state_id, country_id, sa_id, passport, birth_date, gender,
                   first_name, last_name, known_name,
                   genealogy, manager_id, related_distributor_id,
                   active_status, last_inbound_sync_date, last_outbound_sync_date,
                   remote_id, is_credit_check, credit_score,
                   compuscan_checkscore_cpa, compuscan_checkscore_nlr,
                   compuscan_checkscore_date,
                   recruiter_id, recruiter_source,
                   mobile_opt_out, mobile_is_invalid,
                   unverified_first_name, unverified_last_name,
                   unverified_street, unverified_suburb, unverified_city,
                   unverified_zip, unverified_state_id, unverified_country_id
            FROM   hr_employee
            WHERE  employee_type = 'sales_force'
            """,
        )
    else:
        _logger.warning(
            "sales_force_support migration: employee_type column missing from "
            "hr_employee — migrating ALL hr.employee records as sf.members"
        )
        cr.execute(
            """
            SELECT id, name, active, address_home_id, sales_force_code,
                   mobile, mobile_2, street, suburb, city, zip,
                   state_id, country_id, sa_id, passport, birth_date, gender,
                   first_name, last_name, known_name,
                   genealogy, manager_id, related_distributor_id,
                   active_status, last_inbound_sync_date, last_outbound_sync_date,
                   remote_id, is_credit_check, credit_score,
                   compuscan_checkscore_cpa, compuscan_checkscore_nlr,
                   compuscan_checkscore_date,
                   recruiter_id, recruiter_source,
                   mobile_opt_out, mobile_is_invalid,
                   unverified_first_name, unverified_last_name,
                   unverified_street, unverified_suburb, unverified_city,
                   unverified_zip, unverified_state_id, unverified_country_id
            FROM   hr_employee
            """,
        )

    employees = cr.fetchall()
    cols = [d[0] for d in cr.description]
    _logger.info(
        "  Found %d hr.employee record(s) to migrate to sf.member", len(employees)
    )

    # Map old hr.employee.id → new sf.member.id  (for FK updates later)
    employee_to_member = {}

    for row in employees:
        emp = dict(zip(cols, row))
        emp_id = emp["id"]

        # ------------------------------------------------------------------
        # 2a.  Resolve / create res.partner
        # ------------------------------------------------------------------
        partner_id = emp.get("address_home_id")

        if not partner_id:
            # Create a minimal partner
            cr.execute(
                """
                INSERT INTO res_partner
                    (name, active, mobile, street, city, zip,
                     state_id, country_id, create_uid, write_uid,
                     create_date, write_date, type)
                VALUES
                    (%s, %s, %s, %s, %s, %s,
                     %s, %s, 1, 1,
                     NOW(), NOW(), 'contact')
                RETURNING id
                """,
                (
                    emp.get("name") or "Unknown",
                    emp.get("active", True),
                    emp.get("mobile"),
                    emp.get("street"),
                    emp.get("city"),
                    emp.get("zip"),
                    emp.get("state_id"),
                    emp.get("country_id"),
                ),
            )
            partner_id = cr.fetchone()[0]
            _logger.debug("    Created res.partner %d for employee %d", partner_id, emp_id)
        else:
            # Update the existing partner with any missing data
            cr.execute(
                """
                UPDATE res_partner SET
                    name        = COALESCE(name, %s),
                    mobile      = COALESCE(mobile, %s),
                    street      = COALESCE(street, %s),
                    city        = COALESCE(city, %s),
                    zip         = COALESCE(zip, %s),
                    state_id    = COALESCE(state_id, %s),
                    country_id  = COALESCE(country_id, %s)
                WHERE id = %s
                """,
                (
                    emp.get("name"),
                    emp.get("mobile"),
                    emp.get("street"),
                    emp.get("city"),
                    emp.get("zip"),
                    emp.get("state_id"),
                    emp.get("country_id"),
                    partner_id,
                ),
            )

        # ------------------------------------------------------------------
        # 2b.  Create sf.member row
        # ------------------------------------------------------------------
        cr.execute(
            """
            INSERT INTO sf_member (
                partner_id, active, sales_force_code,
                sa_id, passport, birth_date, gender,
                first_name, last_name, known_name,
                genealogy, active_status,
                last_inbound_sync_date, last_outbound_sync_date,
                remote_id, is_credit_check, credit_score,
                compuscan_checkscore_cpa, compuscan_checkscore_nlr,
                compuscan_checkscore_date,
                recruiter_source,
                mobile_opt_out, mobile_is_invalid,
                unverified_first_name, unverified_last_name,
                unverified_street, unverified_suburb, unverified_city,
                unverified_zip, unverified_state_id, unverified_country_id,
                create_uid, write_uid, create_date, write_date
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                1, 1, NOW(), NOW()
            )
            ON CONFLICT (partner_id) DO NOTHING
            RETURNING id
            """,
            (
                partner_id,
                emp.get("active", True),
                emp.get("sales_force_code"),
                emp.get("sa_id"),
                emp.get("passport"),
                emp.get("birth_date"),
                emp.get("gender"),
                emp.get("first_name"),
                emp.get("last_name"),
                emp.get("known_name"),
                emp.get("genealogy"),
                emp.get("active_status"),
                emp.get("last_inbound_sync_date"),
                emp.get("last_outbound_sync_date"),
                emp.get("remote_id"),
                emp.get("is_credit_check", False),
                emp.get("credit_score"),
                emp.get("compuscan_checkscore_cpa"),
                emp.get("compuscan_checkscore_nlr"),
                emp.get("compuscan_checkscore_date"),
                emp.get("recruiter_source"),
                emp.get("mobile_opt_out", False),
                emp.get("mobile_is_invalid", False),
                emp.get("unverified_first_name"),
                emp.get("unverified_last_name"),
                emp.get("unverified_street"),
                emp.get("unverified_suburb"),
                emp.get("unverified_city"),
                emp.get("unverified_zip"),
                emp.get("unverified_state_id"),
                emp.get("unverified_country_id"),
            ),
        )
        result = cr.fetchone()
        if result:
            member_id = result[0]
            employee_to_member[emp_id] = member_id
            _logger.debug("  Migrated hr.employee %d → sf.member %d", emp_id, member_id)
        else:
            _logger.warning(
                "  Skipped hr.employee %d (partner_id %d already in sf.member)",
                emp_id,
                partner_id,
            )

    # ------------------------------------------------------------------
    # 2c.  Resolve manager_id and related_distributor_id (self-referential FKs)
    #      after all base records are created
    # ------------------------------------------------------------------
    for emp_id, member_id in employee_to_member.items():
        cr.execute("SELECT manager_id, related_distributor_id FROM hr_employee WHERE id = %s", (emp_id,))
        row = cr.fetchone()
        if not row:
            continue
        old_manager_id, old_distributor_id = row

        new_manager_id = employee_to_member.get(old_manager_id) if old_manager_id else None
        new_distributor_id = employee_to_member.get(old_distributor_id) if old_distributor_id else None

        if new_manager_id or new_distributor_id:
            cr.execute(
                """
                UPDATE sf_member SET
                    manager_id = COALESCE(%s, manager_id),
                    related_distributor_id = COALESCE(%s, related_distributor_id)
                WHERE id = %s
                """,
                (new_manager_id, new_distributor_id, member_id),
            )

    # ------------------------------------------------------------------
    # 2d.  Resolve recruiter_id (was hr.employee → now sf.member)
    # ------------------------------------------------------------------
    for emp_id, member_id in employee_to_member.items():
        cr.execute("SELECT recruiter_id FROM hr_employee WHERE id = %s", (emp_id,))
        row = cr.fetchone()
        if not row or not row[0]:
            continue
        old_recruiter_id = row[0]
        new_recruiter_id = employee_to_member.get(old_recruiter_id)
        if new_recruiter_id:
            cr.execute(
                "UPDATE sf_member SET recruiter_id = %s WHERE id = %s",
                (new_recruiter_id, member_id),
            )

    _logger.info(
        "  Migrated %d hr.employee records to sf.member", len(employee_to_member)
    )
    return employee_to_member


# ---------------------------------------------------------------------------
# 3.  hr.applicant  →  sf.recruit  migration
# ---------------------------------------------------------------------------
def _migrate_sf_recruits(cr):
    """Migrate hr.applicant records to sf.recruit."""

    cr.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'sf_recruit'"
    )
    if not cr.fetchone()[0]:
        _logger.info(
            "sales_force_support migration: sf_recruit table not yet created, "
            "skipping hr.applicant → sf.recruit data migration"
        )
        return {}

    cr.execute("SELECT COUNT(*) FROM sf_recruit")
    if cr.fetchone()[0] > 0:
        _logger.info(
            "sales_force_support migration: sf_recruit already has records, "
            "skipping hr.applicant → sf.recruit migration"
        )
        return {}

    cr.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'hr_applicant'"
    )
    if not cr.fetchone()[0]:
        _logger.info(
            "sales_force_support migration: hr_applicant table not found, skipping"
        )
        return {}

    _logger.info(
        "sales_force_support migration: migrating hr.applicant → sf.recruit …"
    )

    cr.execute(
        """
        SELECT id, active, address_home_id,
               first_name, last_name, partner_name,
               mobile, street, suburb, city, zip,
               state_id, country_id,
               sa_id, passport, birth_date, gender,
               known_name, sales_force_code,
               genealogy, stage_id,
               manager_id, related_distributor_id, consultant_id,
               is_credit_check, credit_score,
               compuscan_checkscore_cpa, compuscan_checkscore_nlr,
               compuscan_checkscore_date,
               recruiter_id, recruiter_source,
               mobile_opt_out, mobile_is_invalid,
               address_verified,
               last_contact_date, last_contact_type,
               remote_id,
               unverified_first_name, unverified_last_name,
               unverified_street, unverified_suburb, unverified_city,
               unverified_zip, unverified_state_id, unverified_country_id
        FROM hr_applicant
        """
    )
    applicants = cr.fetchall()
    cols = [d[0] for d in cr.description]
    _logger.info(
        "  Found %d hr.applicant record(s) to migrate to sf.recruit", len(applicants)
    )

    applicant_to_recruit = {}

    for row in applicants:
        app = dict(zip(cols, row))
        app_id = app["id"]

        # Resolve / create res.partner
        partner_id = app.get("address_home_id")
        display_name = (
            " ".join(filter(None, [app.get("first_name"), app.get("last_name")]))
            or app.get("partner_name")
            or "Unknown Recruit"
        )

        if not partner_id:
            cr.execute(
                """
                INSERT INTO res_partner
                    (name, active, mobile, street, city, zip,
                     state_id, country_id, create_uid, write_uid,
                     create_date, write_date, type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 1, NOW(), NOW(), 'contact')
                RETURNING id
                """,
                (
                    display_name,
                    app.get("active", True),
                    app.get("mobile"),
                    app.get("street"),
                    app.get("city"),
                    app.get("zip"),
                    app.get("state_id"),
                    app.get("country_id"),
                ),
            )
            partner_id = cr.fetchone()[0]

        cr.execute(
            """
            INSERT INTO sf_recruit (
                partner_id, active,
                first_name, last_name, known_name,
                sa_id, passport, birth_date, gender,
                sales_force_code, genealogy,
                stage_id, address_verified,
                is_credit_check, credit_score,
                compuscan_checkscore_cpa, compuscan_checkscore_nlr,
                compuscan_checkscore_date,
                recruiter_source,
                mobile_opt_out, mobile_is_invalid,
                remote_id,
                last_contact_date, last_contact_type,
                unverified_first_name, unverified_last_name,
                unverified_street, unverified_suburb, unverified_city,
                unverified_zip, unverified_state_id, unverified_country_id,
                create_uid, write_uid, create_date, write_date
            ) VALUES (
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s,
                %s,
                %s, %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                1, 1, NOW(), NOW()
            )
            ON CONFLICT (partner_id) DO NOTHING
            RETURNING id
            """,
            (
                partner_id,
                app.get("active", True),
                app.get("first_name"),
                app.get("last_name"),
                app.get("known_name"),
                app.get("sa_id"),
                app.get("passport"),
                app.get("birth_date"),
                app.get("gender"),
                app.get("sales_force_code"),
                app.get("genealogy"),
                app.get("stage_id"),
                app.get("address_verified", False),
                app.get("is_credit_check", False),
                app.get("credit_score"),
                app.get("compuscan_checkscore_cpa"),
                app.get("compuscan_checkscore_nlr"),
                app.get("compuscan_checkscore_date"),
                app.get("recruiter_source"),
                app.get("mobile_opt_out", False),
                app.get("mobile_is_invalid", False),
                app.get("remote_id"),
                app.get("last_contact_date"),
                app.get("last_contact_type"),
                app.get("unverified_first_name"),
                app.get("unverified_last_name"),
                app.get("unverified_street"),
                app.get("unverified_suburb"),
                app.get("unverified_city"),
                app.get("unverified_zip"),
                app.get("unverified_state_id"),
                app.get("unverified_country_id"),
            ),
        )
        result = cr.fetchone()
        if result:
            recruit_id = result[0]
            applicant_to_recruit[app_id] = recruit_id

    _logger.info(
        "  Migrated %d hr.applicant records to sf.recruit",
        len(applicant_to_recruit),
    )
    return applicant_to_recruit


# ---------------------------------------------------------------------------
# 4.  Update FK references in dependent tables
# ---------------------------------------------------------------------------
def _update_fk_references(cr, employee_to_member, applicant_to_recruit):
    """
    Update FK columns in models that previously pointed at hr.employee /
    hr.applicant to now point at sf.member / sf.recruit.

    Tables and columns are listed explicitly to be safe.
    """
    if not employee_to_member and not applicant_to_recruit:
        return

    _logger.info(
        "sales_force_support migration: updating FK references …"
    )

    def _update_fk(table, column, id_map):
        """Update each row in `table.column` using the id_map."""
        if not id_map:
            return
        cr.execute(
            f"SELECT COUNT(*) FROM information_schema.columns "
            f"WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        if not cr.fetchone()[0]:
            _logger.debug("  Skipping %s.%s (column not found)", table, column)
            return
        for old_id, new_id in id_map.items():
            cr.execute(
                f"UPDATE {table} SET {column} = %s WHERE {column} = %s",
                (new_id, old_id),
            )
        _logger.debug("  Updated %s.%s", table, column)

    # bb.payin.sheet
    _update_fk("bb_payin_sheet", "distributor_id", employee_to_member)
    _update_fk("bb_payin_sheet", "manager_id", employee_to_member)

    # bb.payin.sheet.line
    _update_fk("bb_payin_sheet_line", "consultant_id", employee_to_member)
    _update_fk("bb_payin_sheet_line", "manager_id", employee_to_member)

    # payin.distributor
    _update_fk("payin_distributor", "distributor_id", employee_to_member)

    # payin.distributor.line
    _update_fk("payin_distributor_line", "manager_id", employee_to_member)

    # bb.payin.history
    _update_fk("bb_payin_history", "employee_id", employee_to_member)
    _update_fk("bb_payin_history", "manager_id", employee_to_member)
    _update_fk("bb_payin_history", "promoted_by", employee_to_member)

    # sale.order
    _update_fk("sale_order", "consultant_id", employee_to_member)

    # purchase.order
    _update_fk("purchase_order", "buyer_id", employee_to_member)

    # sf.distribution
    _update_fk("sf_distribution", "sales_force_member_id", employee_to_member)

    # status.audit.trail
    _update_fk("status_audit_trail", "member_id", employee_to_member)

    # res.partner consultant/manager/distributor_id fields
    _update_fk("res_partner", "consultant_id", employee_to_member)
    _update_fk("res_partner", "manager_id", employee_to_member)
    _update_fk("res_partner", "distributor_id", employee_to_member)

    # sf.recruit (recruiter / manager / distributor references)
    _update_fk("sf_recruit", "recruiter_id", employee_to_member)
    _update_fk("sf_recruit", "manager_id", employee_to_member)
    _update_fk("sf_recruit", "related_distributor_id", employee_to_member)
    _update_fk("sf_recruit", "consultant_id", employee_to_member)

    _logger.info("sales_force_support migration: FK references updated.")


# ---------------------------------------------------------------------------
# 5.  Update view_model field on res.partner
# ---------------------------------------------------------------------------
def _update_view_model(cr, employee_to_member, applicant_to_recruit):
    """
    res.partner.view_model was 'hr.employee' / 'hr.applicant' in the old code.
    Update to 'sf.member' / 'sf.recruit'.
    Also update view_res_id to the new IDs.
    """
    cr.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'res_partner' AND column_name = 'view_model'"
    )
    if not cr.fetchone()[0]:
        return

    # hr.employee → sf.member
    for old_id, new_id in employee_to_member.items():
        cr.execute(
            """
            UPDATE res_partner
            SET    view_model = 'sf.member', view_res_id = %s
            WHERE  view_model = 'hr.employee' AND view_res_id = %s
            """,
            (new_id, old_id),
        )

    # hr.applicant → sf.recruit
    for old_id, new_id in applicant_to_recruit.items():
        cr.execute(
            """
            UPDATE res_partner
            SET    view_model = 'sf.recruit', view_res_id = %s
            WHERE  view_model = 'hr.applicant' AND view_res_id = %s
            """,
            (new_id, old_id),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def migrate(cr, version):
    """Called by Odoo's migration framework."""
    if not version:
        # Fresh install — nothing to migrate
        return

    _logger.info(
        "sales_force_support pre-migration starting (from version %s)", version
    )

    # 1. Config parameters
    _migrate_config_params(cr)

    # 2 & 3. Model data
    employee_to_member = _migrate_sf_members(cr)
    applicant_to_recruit = _migrate_sf_recruits(cr)

    # 4 & 5. FK and view_model updates
    _update_fk_references(cr, employee_to_member, applicant_to_recruit)
    _update_view_model(cr, employee_to_member, applicant_to_recruit)

    _logger.info("sales_force_support pre-migration complete.")
