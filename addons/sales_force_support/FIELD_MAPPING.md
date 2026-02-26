# Field Mapping: Legacy Modules → `sales_force_support`

**Audience:** Data Science / BI team maintaining external reports and dashboards.
**Scope:** Every model rename, table rename, field rename, FK target change, and value-set change
introduced by the consolidation of the eight legacy Odoo modules into `sales_force_support`.

---

## 1. Database Table Renames

The most impactful change for SQL-based reports: two core tables are replaced entirely.

| Legacy table | New table | Notes |
|---|---|---|
| `hr_employee` | `sf_member` | Rows migrated by pre-migrate script |
| `hr_applicant` | `sf_recruit` | Rows migrated by pre-migrate script |
| `hr_recruitment_stage` | `sf_recruit_stage` | New table; old stage data not auto-migrated |
| `hr_job` | *(removed)* | Replaced by `genealogy` column on `sf_member` / `sf_recruit` |

All other tables are **unchanged** (`bb_payin_sheet`, `payin_distributor`, `bb_payin_history`, `res_partner`, etc.). Their **FK columns** pointing to `hr_employee` now point to `sf_member` — see §4.

---

## 2. Core Model / Table Mapping

### 2.1 `hr.employee` → `sf.member`

| Attribute | Legacy | New |
|---|---|---|
| Odoo model name | `hr.employee` | `sf.member` |
| PostgreSQL table | `hr_employee` | `sf_member` |
| Primary key | `id` | `id` |
| Delegation table | `res_partner` (via `partner_id`) | `res_partner` (via `partner_id`) |
| Chatter mixin | `mail.thread`, `mail.activity.mixin` | same |

### 2.2 `hr.applicant` → `sf.recruit`

| Attribute | Legacy | New |
|---|---|---|
| Odoo model name | `hr.applicant` | `sf.recruit` |
| PostgreSQL table | `hr_applicant` | `sf_recruit` |
| Primary key | `id` | `id` |
| Delegation table | `res_partner` (via `partner_id`) | `res_partner` (via `partner_id`) |
| Stage model | `hr.recruitment.stage` → `hr_recruitment_stage` | `sf.recruit.stage` → `sf_recruit_stage` |

### 2.3 `hr.recruitment.stage` → `sf.recruit.stage`

| Attribute | Legacy | New |
|---|---|---|
| Odoo model name | `hr.recruitment.stage` | `sf.recruit.stage` |
| PostgreSQL table | `hr_recruitment_stage` | `sf_recruit_stage` |
| FK in `sf_recruit` | `stage_id → hr_recruitment_stage.id` | `stage_id → sf_recruit_stage.id` |

### 2.4 `hr.job` → removed (inline `genealogy` Selection)

`hr.job` no longer exists. The genealogy/rank of a member is stored as a `Selection` field
directly on `sf_member` and `sf_recruit`. See §3 for the full value mapping.

---

## 3. Genealogy Value Mapping

Previously `job_id` was a Many2one to `hr.job`. Reports that joined on `hr_job.name`
must now filter on the `genealogy` column in `sf_member` or `sf_recruit`.

| `hr_job.name` (legacy) | `genealogy` value (new) | Notes |
|---|---|---|
| `Distributor` | `distributor` | |
| `Distributor Partner` | `distributor_partner` | |
| `Prospective Distributor` | `prospective_distributor` | |
| `Manager` | `manager` | |
| `Manager Partner` | `manager_partner` | |
| `Prospective Manager` | `prospective_manager` | |
| `Consultant` | `consultant` | |
| `Potential Consultant` | `potential_consultant` | |
| `Support Office` | `support_office` | |

**SQL translation example:**
```sql
-- Legacy
SELECT e.name, j.name AS genealogy
FROM hr_employee e
JOIN hr_job j ON j.id = e.job_id
WHERE j.name = 'Manager'
  AND e.employee_type = 'sales_force';

-- New
SELECT m.id, p.name, m.genealogy
FROM sf_member m
JOIN res_partner p ON p.id = m.partner_id
WHERE m.genealogy = 'manager';
```

> **Note:** The `employee_type = 'sales_force'` filter is no longer needed because
> `sf_member` contains only sales-force members by design.

---

## 4. Foreign Key Column Changes

Tables whose FK columns previously pointed to `hr_employee` now point to `sf_member`.
Column **names are unchanged**; only the target table changes.

### `bb_payin_sheet`

| Column | Old FK target | New FK target |
|---|---|---|
| `distributor_id` | `hr_employee.id` | `sf_member.id` |
| `manager_id` | `hr_employee.id` | `sf_member.id` |

### `bb_payin_sheet_line`

| Column | Old FK target | New FK target |
|---|---|---|
| `consultant_id` | `hr_employee.id` | `sf_member.id` |

### `payin_distributor`

| Column | Old FK target | New FK target |
|---|---|---|
| `distributor_id` | `hr_employee.id` | `sf_member.id` |

### `payin_distributor_line`

| Column | Old FK target | New FK target |
|---|---|---|
| `manager_id` | `hr_employee.id` | `sf_member.id` |

### `bb_payin_history`

| Column | Old FK target | New FK target |
|---|---|---|
| `employee_id` | `hr_employee.id` | `sf_member.id` |
| `manager_id` | `hr_employee.id` | `sf_member.id` |
| `promoted_by` | `hr_employee.id` | `sf_member.id` |

### `sale_order`

| Column | Old FK target | New FK target |
|---|---|---|
| `employee_id` *(if present)* | `hr_employee.id` | `sf_member.id` |

### `purchase_order`

| Column | Old FK target | New FK target |
|---|---|---|
| `employee_id` *(if present)* | `hr_employee.id` | `sf_member.id` |

### `sf_distribution`

| Column | Old FK target | New FK target |
|---|---|---|
| `manager_id` | `hr_employee.id` | `sf_member.id` |

### `status_audit_trail`

| Column | Old FK target | New FK target |
|---|---|---|
| `employee_id` | `hr_employee.id` | `sf_member.id` |

### `res_partner`

| Column | Old FK target | New FK target |
|---|---|---|
| `consultant_id` | `hr_employee.id` | `sf_member.id` |
| `manager_id` | `hr_employee.id` | `sf_member.id` |
| `related_distributor_id` | `hr_employee.id` | `sf_member.id` |
| `recruiter_id` | `hr_employee.id` | `sf_member.id` |
| `related_sfm_id` | `hr_employee.id` | `sf_member.id` |

### `sf_recruit`

| Column | Old FK target | New FK target |
|---|---|---|
| `manager_id` | `hr_employee.id` | `sf_member.id` |
| `recruiter_id` | `hr_employee.id` | `sf_member.id` |
| `consultant_id` | `hr_employee.id` | `sf_member.id` |
| `related_distributor_id` | `hr_employee.id` | `sf_member.id` |
| `related_prospective_manager_id` | `hr_employee.id` | `sf_member.id` |
| `related_prospective_distributor_id` | `hr_employee.id` | `sf_member.id` |
| `stage_id` | `hr_recruitment_stage.id` | `sf_recruit_stage.id` |

---

## 5. Field Renames

Fields whose **column name** changed (same table, different column).

### `bb_payin_history`

| Old column | New column | Type | Notes |
|---|---|---|---|
| `current_job_id` | `current_genealogy` | `integer` → `varchar` | Was Many2one to `hr.job`; now Selection string |

> When `current_job_id` was `hr_job.id = X` (e.g. id for "Manager"), `current_genealogy`
> is now the string `'manager'`. Use the value mapping table in §3.

### `hr_applicant` → `sf_recruit` field renames

| Old column (`hr_applicant`) | New column (`sf_recruit`) | Notes |
|---|---|---|
| `create_employee` | `create_member` | Boolean flag on stage: "auto-promote to sf.member" |

### `sf_member` — new columns vs legacy `hr_employee`

These columns exist on `sf_member` but did **not** exist on legacy `hr_employee` (added from
`bb_allocate`, `bbb_sales_force_genealogy`, or as new fields):

| New column | Type | Source module | Description |
|---|---|---|---|
| `genealogy` | `varchar` | *replaced hr.job* | Selection: see §3 |
| `job_name` | `varchar` | computed | Human-readable genealogy label |
| `related_genealogy` | `varchar` | computed/related | Alias of `genealogy` |
| `previous_genealogy` | `varchar` | new | Previous genealogy before last change |
| `remote_id` | `integer` | `bbb_sales_force_genealogy` | Remote sync PK |
| `last_outbound_sync_date` | `timestamp` | `bbb_sales_force_genealogy` | — |
| `last_inbound_sync_date` | `timestamp` | `bbb_sales_force_genealogy` | — |
| `distribution_id` | `integer` → `sf_distribution.id` | `bbb_sales_force_genealogy` | — |
| `recruiter_sales_force_code` | `varchar` | new | Related field |
| `distributor_sales_force_code` | `varchar` | new | Related field |
| `promoter_sales_force_code` | `varchar` | new | Related field |
| `demoter_id` | `integer` → `sf_member.id` | new | Who demoted this member |
| `demoter_sales_force_code` | `varchar` | new | — |
| `previous_manager_id` | `integer` → `sf_member.id` | new | — |
| `previous_distributor_id` | `integer` → `sf_member.id` | new | — |
| `promotion_date` | `date` | new | — |
| `promotion_effective_date` | `date` | new | — |
| `promotion_reason` | `varchar` | new | Selection |
| `demotion_date` | `date` | new | — |
| `demotion_effective_date` | `date` | new | — |
| `demotion_reason` | `varchar` | new | Selection |
| `blacklisted_date` | `date` | new | — |
| `unblacklist_date` | `date` | new | — |
| `suspended_date` | `date` | new | — |
| `unsuspended_date` | `date` | new | — |
| `move_date` | `date` | new | Last organisational move date |
| `move_reason` | `varchar` | new | Selection |
| `last_app_login_date` | `timestamp` | new | Mobile app login |
| `days_since_last_login` | `integer` | computed | — |
| `manager_blacklist` | `varchar` | `bb_allocate` | — |
| `linked_consultant_ids` | One2many | new | — |
| `status_trail_ids` | One2many | new | Points to `bb_payin_history` |
| `payin_count` | `integer` | computed | — |

### `sf_recruit` — new columns vs legacy `hr_applicant`

These columns exist on `sf_recruit` but did **not** exist on legacy `hr_applicant`:

| New column | Type | Source | Description |
|---|---|---|---|
| `genealogy` | `varchar` | new | Same Selection as `sf_member` |
| `job_name` | `varchar` | computed | — |
| `member_id` | `integer` → `sf_member.id` | new | Linked sales force member |
| `remote_id` | `integer` | new | — |
| `mobile_app_id` | `integer` | new | Mobile app reference |
| `is_interested` | `bool` | new | Onboarding step |
| `interested_date` | `date` | new | — |
| `mobile_confirmed` | `bool` | new | Onboarding step |
| `mobile_confirm_date` | `date` | new | — |
| `induction_meeting_invited` | `bool` | new | — |
| `induction_meeting_invite_date` | `date` | new | — |
| `induction_meeting_scheduled_date` | `date` | new | — |
| `induction_meeting_attended` | `bool` | new | — |
| `induction_meeting_attendance_date` | `date` | new | — |
| `documents_submitted` | `bool` | new | — |
| `documents_submitted_date` | `date` | new | — |
| `onboarding_started` | `bool` | new | — |
| `onboarding_start_date` | `date` | new | — |
| `credit_check_permission_granted` | `bool` | new | — |
| `credit_check_permission_date` | `date` | new | — |
| `credit_check_generated` | `bool` | new | — |
| `credit_check_generated_date` | `date` | new | — |
| `consumerview_address_confirmed` | `bool` | new | — |
| `consumerview_address_confirm_date` | `date` | new | — |
| `interview_started` | `bool` | new | — |
| `interview_start_date` | `date` | new | — |
| `interview_status` | `varchar` | new | — |
| `onboarding_completed` | `bool` | new | — |
| `onboarding_complete_date` | `date` | new | — |
| `move_date` | `date` | new | — |
| `manager_blacklist` | `varchar` | `bb_allocate` | — |

---

## 6. `res_partner` — New Columns

`res_partner` is extended by the consolidated module. These columns are **added** to the
existing table (no columns removed):

| New column | Type | Source module | Description |
|---|---|---|---|
| `view_model` | `varchar` | `botle_buhle_custom` | Was `'hr.employee'`/`'hr.applicant'`; now `'sf.member'`/`'sf.recruit'` |
| `view_res_id` | `integer` | `botle_buhle_custom` | ID in the `view_model` table |
| `related_sfm_id` | `integer` → `sf_member.id` | new | — |
| `related_sfm_code` | `varchar` | related | — |
| `manager_sfm_code` | `varchar` | related | — |
| `manager_mobile` | `varchar` | related | — |
| `compuscan_checkscore_cpa` | `varchar` | `partner_compuscan` | — |
| `compuscan_checkscore_nlr` | `varchar` | `partner_compuscan` | — |
| `compuscan_checkscore_date` | `timestamp` | `partner_compuscan` | — |
| `compuscan_checkscore_risk` | `varchar` | `partner_compuscan` | Selection |
| `consumerview_ref` | `varchar` | `partner_consumerview` | — |
| `unverified_city` | `varchar` | `partner_consumerview` | — |
| `unverified_address` | `varchar` | `partner_consumerview` | — |
| `unverified_state_id` | `integer` | `partner_consumerview` | — |
| `unverified_country_id` | `integer` | `partner_consumerview` | — |
| `unverified_street` | `varchar` | `partner_consumerview` | — |
| `unverified_suburb` | `varchar` | `partner_consumerview` | — |
| `unverified_first_name` | `varchar` | `partner_consumerview` | — |
| `unverified_last_name` | `varchar` | `partner_consumerview` | — |
| `unverified_zip` | `varchar` | `partner_consumerview` | — |
| `address_verified` | `bool` | `partner_consumerview` | — |
| `consultant_blacklist` | `varchar` | `bb_allocate` | — |
| `distribution_id` | `integer` → `sf_distribution.id` | `bbb_sales_force_genealogy` | — |
| `remote_id` | `integer` | `bbb_sales_force_genealogy` | — |
| `last_outbound_sync_date` | `timestamp` | `bbb_sales_force_genealogy` | — |
| `last_inbound_sync_date` | `timestamp` | `bbb_sales_force_genealogy` | — |
| `is_rsa_id_valid` | `bool` | `bbb_sales_force_genealogy` | — |
| `create_date_bb` | `timestamp` | `bbb_sales_force_genealogy` | — |
| `country_name` | `varchar` | computed | Derived from mobile country code |

### `view_model` value change

Reports that filter or pivot on `res_partner.view_model` must update their filter values:

| Old value | New value |
|---|---|
| `'hr.employee'` | `'sf.member'` |
| `'hr.applicant'` | `'sf.recruit'` |
| `'res.partner'` | `'res.partner'` *(unchanged)* |

---

## 7. `bb_payin_history` — Complete Column Reference

| Column | Type | Legacy source | Notes |
|---|---|---|---|
| `id` | `integer` | unchanged | PK |
| `payin_date` | `date` | unchanged | Month/Year |
| `employee_id` | `integer` | `hr_employee.id` | → **`sf_member.id`** (FK target changed) |
| `sales_force_code` | `varchar` | related | unchanged |
| `current_genealogy` | `varchar` | **renamed** from `current_job_id` | Was `integer` FK; now Selection string |
| `manager_code` | `varchar` | unchanged | |
| `distributor_code` | `varchar` | unchanged | |
| `active_status` | `varchar` | unchanged | Selection |
| `promoted_this_month` | `bool` | unchanged | |
| `personal_bbb_sale` | `float8` | unchanged | |
| `personal_puer_sale` | `float8` | unchanged | |
| `promoted_by` | `integer` | `hr_employee.id` | → **`sf_member.id`** |
| `manager_id` | `integer` | `hr_employee.id` | → **`sf_member.id`** |
| `name` | `varchar` | related | unchanged |
| `team_bbb_sales` | `float8` | unchanged | |
| `team_puer_sales` | `float8` | unchanged | |
| `total_team_sales` | `float8` | computed/stored | unchanged |
| `total_personal_sales` | `float8` | computed/stored | unchanged |
| `active_80` | `bool` | unchanged | |
| `team_80` | `bool` | unchanged | |
| `personal_80` | `bool` | unchanged | |
| *(all promotion/flag columns)* | various | unchanged | |

---

## 8. `bb_payin_sheet` — Complete Column Reference

Columns **unchanged** except FK targets:

| Column | Type | FK target change |
|---|---|---|
| `distributor_id` | `integer` | `hr_employee` → **`sf_member`** |
| `manager_id` | `integer` | `hr_employee` → **`sf_member`** |
| `payin_line_existing_consultant_ids` *(m2m)* | — | `hr_employee` → **`sf_member`** |
| All other columns | — | unchanged |

---

## 9. `bb_payin_sheet_line` — Complete Column Reference

| Column | FK target change |
|---|---|
| `consultant_id` | `hr_employee` → **`sf_member`** |
| All other columns | unchanged |

---

## 10. `payin_distributor` — Complete Column Reference

| Column | FK target change |
|---|---|
| `distributor_id` | `hr_employee` → **`sf_member`** |
| All other columns | unchanged |

---

## 11. `payin_distributor_line` — Complete Column Reference

| Column | FK target change |
|---|---|
| `manager_id` | `hr_employee` → **`sf_member`** |
| All other columns | unchanged |

---

## 12. Selection Field Value Reference

### `active_status` (on `sf_member`, `sf_recruit`, `bb_payin_history`)

Values unchanged from legacy:

| Value | Label |
|---|---|
| `potential_consultant` | Potential Consultant |
| `pay_in_sheet_pending` | Pay-In Sheet Pending |
| `active1` | Active 1 |
| `active2` | Active 2 |
| `active3` | Active 3 |
| `active4` | Active 4 |
| `active5` | Active 5 |
| `active6` | Active 6 |
| `inactive12` | Inactive 12 |
| `inactive18` | Inactive 18 |
| `suspended` | Suspended |
| `blacklisted` | Internally Blacklisted |

### `recruitment_method` (on `sf_member`, `sf_recruit`)

| Value | Label |
|---|---|
| `pay_in_sheet` | Pay-In Sheet |
| `website` | Website |
| `sms_shortcode` | SMS Shortcode |
| `whatsapp` | WhatsApp |
| `app` | App |
| `contact_center` | Contact Center |
| `other` | Other |
| `recruiting_link` | Recruiting Link |

### `registration_channel` (on `sf_recruit`)

| Value | Label |
|---|---|
| `registration_form` | Registration Form |
| `contact_centre` | Contact Centre |
| `manual_capture` | Manual Capture (Pay-In Sheets) |

### `bb_payin_sheet.state` / `payin_distributor.state`

Values unchanged:

| Value | Label |
|---|---|
| `new` | New |
| `registered` | Registered |
| `captured` | Captured |
| `verified` | Verified |

---

## 13. Quick SQL Migration Cheat Sheet

```sql
-- Joining sf.member instead of hr.employee
-- Old:
FROM bb_payin_sheet s
JOIN hr_employee e ON e.id = s.distributor_id
JOIN res_partner p ON p.id = e.partner_id

-- New (table change only; column names unchanged):
FROM bb_payin_sheet s
JOIN sf_member e ON e.id = s.distributor_id
JOIN res_partner p ON p.id = e.partner_id

-- -------------------------------------------------------
-- Genealogy filter (no longer a join)
-- Old:
FROM hr_employee e
JOIN hr_job j ON j.id = e.job_id
WHERE j.name = 'Distributor'

-- New:
FROM sf_member
WHERE genealogy = 'distributor'

-- -------------------------------------------------------
-- Pay-In History — renamed column
-- Old:
SELECT h.employee_id, j.name AS genealogy
FROM bb_payin_history h
JOIN hr_employee e ON e.id = h.employee_id
JOIN hr_job j ON j.id = h.current_job_id

-- New:
SELECT h.employee_id, h.current_genealogy
FROM bb_payin_history h
-- (no hr_job join needed)

-- -------------------------------------------------------
-- res_partner view_model filter
-- Old: WHERE view_model = 'hr.employee'
-- New: WHERE view_model = 'sf.member'

-- Old: WHERE view_model = 'hr.applicant'
-- New: WHERE view_model = 'sf.recruit'
```

---

## 14. Removed Tables / Columns

| What was removed | Replacement |
|---|---|
| Table `hr_job` | `genealogy` column (varchar) on `sf_member` and `sf_recruit` |
| Table `hr_recruitment_stage` | Table `sf_recruit_stage` |
| `hr_employee.job_id` column | `sf_member.genealogy` column |
| `hr_applicant.job_id` column | `sf_recruit.genealogy` column |
| `hr_applicant.stage_id → hr_recruitment_stage` | `sf_recruit.stage_id → sf_recruit_stage` |
| `hr_applicant.create_employee` column | `sf_recruit.create_member` column |
| `bb_payin_history.current_job_id` column | `bb_payin_history.current_genealogy` column |
| `hr_employee.employee_type` filter *(used in domains)* | Not needed — `sf_member` is sales-force only |
| `hr_employee.sales_force` boolean filter *(used in domains)* | Not needed — same reason |
