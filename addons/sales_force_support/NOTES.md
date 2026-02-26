# sales_force_support — Consolidation Notes

## Overview

`sales_force_support` is a single Odoo 17 module that replaces eight legacy modules:

| Legacy module | What it provided |
|---|---|
| `botle_buhle_custom` | `sf.member` (was `hr.employee`), partner extensions, views, wizards |
| `bbb_sales_force_genealogy` | Genealogy sync, `sf.distribution`, `sf.mapping.field`, consultant wizards |
| `bb_payin` | Pay-In Sheet models, reports, wizards, controllers |
| `bb_allocate` | Geographic allocation fields (merged into `sf.member` / `res.partner`) |
| `bb_chatbot` | WhatsApp chatbot controller |
| `bbb_sales_force` | (empty views — no functional code) |
| `partner_compuscan` | Compuscan CheckScore fields on `res.partner` |
| `partner_consumerview` | ConsumerView KYC fields + resolve wizard on `res.partner` |

---

## Key Architectural Changes

### 1. `hr.employee` → `sf.member`

`sf.member` is a new standalone model (`_name = "sf.member"`) that uses
`_inherits = {"res.partner": "partner_id"}` (delegation inheritance).

- No longer extends `hr.employee` — the `hr` / `hr_recruitment` dependencies are removed.
- Fields previously on `hr.employee` (genealogy, sales_force_code, manager_id, …) now live
  directly on `sf.member`.
- The `employee_type = 'sales_force'` filter used in legacy domains is gone.

### 2. `hr.applicant` → `sf.recruit`

`sf.recruit` is a new standalone model (`_name = "sf.recruit"`) that also uses
`_inherits = {"res.partner": "partner_id"}`.

- Replaces `hr.applicant` for the sales-force recruitment pipeline.
- Stage model is `sf.recruit.stage` (replaces `hr.recruitment.stage`).

### 3. `hr.job` → `genealogy` Selection field

The Many2one `job_id` on `hr.employee` is replaced by a `genealogy` Selection field on `sf.member`:

| Legacy `job_id.name` value | New `genealogy` value |
|---|---|
| Distributor | `distributor` |
| Distributor Partner | `distributor_partner` |
| Prospective Distributor | `prospective_distributor` |
| Manager | `manager` |
| Manager Partner | `manager_partner` |
| Prospective Manager | `prospective_manager` |
| Consultant | `consultant` |
| Potential Consultant | `potential_consultant` |
| Support Office | `support_office` |

Legacy domain pattern:
```python
[('job_id.name', '=', 'Manager'), ('employee_type', '=', 'sales_force')]
```
New pattern:
```python
[('genealogy', '=', 'manager')]
```

### 4. `view_model` field on `res.partner`

`res.partner.view_model` previously stored `"hr.employee"` or `"hr.applicant"`.
It now stores `"sf.member"` or `"sf.recruit"`. The migration script updates this.

---

## Module Structure

```
sales_force_support/
├── __manifest__.py
├── __init__.py
├── NOTES.md                       ← this file
├── data/
│   └── data.xml                   # sequences, cron jobs, config records
├── migrations/
│   └── 17.0.1.0.0/
│       ├── pre-migrate.py         # config param migration, sf.member/sf.recruit data copy
│       └── post-migrate.py        # ir.model.data XML-ID renames, rule recomputation
├── models/
│   ├── custom/                    # new / standalone models
│   │   ├── sf_member.py           # sf.member (replaces hr.employee)
│   │   ├── sf_recruit.py          # sf.recruit + required.field.state (replaces hr.applicant)
│   │   ├── sf_recruit_stage.py    # sf.recruit.stage (replaces hr.recruitment.stage)
│   │   ├── sf_distribution.py     # sf.distribution, sf.mapping.field, user.otp
│   │   ├── bb_payin_sheet.py      # bb.payin.sheet, bb.payin.sheet.line, payin.distributor, …
│   │   ├── bb_payin_history.py    # bb.payin.history (current_genealogy replaces current_job_id)
│   │   ├── bb_payin_sheets_report.py
│   │   ├── bb_payin_report_tracker.py
│   │   ├── hr_contacts.py
│   │   ├── interview_decline_reasons.py
│   │   ├── promotion_rules.py
│   │   ├── res_communication.py
│   │   ├── res_vetting.py
│   │   ├── status_audit_trail.py
│   └── inherited/                 # extensions of standard Odoo models
│       ├── res_partner.py         # + Compuscan, ConsumerView, allocation fields
│       ├── res_company.py         # + ConsumerView env setting
│       ├── res_config_settings.py # + all legacy config settings fields
│       ├── res_country.py         # + country-level fields
│       ├── res_users.py
│       ├── sale_order.py
│       ├── purchase_order.py
│       └── voip_call.py
├── controllers/
│   ├── payin_controller.py        # /payin_sheet_reports, /xlsx_reports
│   ├── sync_controller.py         # /sales_force POST/PUT inbound sync
│   └── chatbot_controller.py      # /chatbot/... WhatsApp webhook
├── wizards/
│   ├── capture.py / capture.xml
│   ├── payin_wizard.py / payin_wizard_view.xml
│   ├── payin_report_wizard.py / payin_report_wizard.xml
│   ├── consultant_blacklist_wizard.py / _view.xml
│   ├── consultant_create_wizard.py / _view.xml + display_created_consultant.xml
│   ├── consultant_move_wizard.py / _view.xml
│   ├── consultant_promote_wizard.py / _view.xml
│   ├── consultant_search.py / consultant_search_view.xml
│   └── partner_consumerview_resolve.py / _views.xml
├── reports/
│   ├── captured_payin_sheet_report.py   # _get_report_values for captured sheets
│   ├── payin_report_view.xml            # ir.actions.report records (3700+ lines)
│   ├── payin_report_all_view.xml        # QWeb templates for all sheet variants
│   └── distributor_summary_form.xml     # QWeb template for distributor summary
├── security/
│   ├── groups.xml                 # all groups (sf, payin, compuscan, consumerview, voip)
│   └── ir.model.access.csv        # 40 access rules
├── views/
│   ├── sf_member_views.xml
│   ├── sf_recruit_views.xml
│   ├── promotion_rules_views.xml
│   ├── payin_history_views.xml
│   ├── payin_views.xml
│   ├── res_partner_views.xml
│   ├── res_country_views.xml
│   ├── res_company_views.xml
│   ├── res_config_settings_views.xml
│   ├── res_users_views.xml
│   ├── sale_order_views.xml
│   └── purchase_order_views.xml
└── static/src/
    ├── css/  (kanban_ribbon, payin, tree_header)
    ├── js/   (16 JS files)
    └── xml/  (5 OWL/QWeb templates)
```

---

## Configuration Parameter Migration

All `ir.config_parameter` keys are renamed by `pre-migrate.py`:

| Old key | New key |
|---|---|
| `bbb_sales_force_genealogy.enable_outbound_synchronisation` | `sales_force_support.enable_outbound_synchronisation` |
| `bbb_sales_force_genealogy.enable_inbound_synchronisation` | `sales_force_support.enable_inbound_synchronisation` |
| `bbb_sales_force_genealogy.outbound_url` | `sales_force_support.outbound_url` |
| `bbb_sales_force_genealogy.outbound_database` | `sales_force_support.outbound_database` |
| `bbb_sales_force_genealogy.outbound_login` | `sales_force_support.outbound_login` |
| `bbb_sales_force_genealogy.outbound_password` | `sales_force_support.outbound_password` |
| `botle_buhle_custom.whatsapp_bbbot_sender_token` | `sales_force_support.whatsapp_bbbot_sender_token` |
| `botle_buhle_custom.whatsapp_bbbot_sender_namespace` | `sales_force_support.whatsapp_bbbot_sender_namespace` |
| `botle_buhle_custom.whatsapp_bbbot_sender_phone_number_id` | `sales_force_support.whatsapp_bbbot_sender_phone_number_id` |
| `bb_payin.report_print_count` | `sales_force_support.report_print_count` |
| `bb_payin.voip_access_group_ids` | `sales_force_support.voip_access_group_ids` |
| `bb_payin.payin_active_status_reference_date` | `sales_force_support.payin_active_status_reference_date` |
| `bb_payin.telviva_*` (6 keys) | `sales_force_support.telviva_*` |

---

## Known Differences from Legacy Modules

### Removed features
- **`hr.job` model**: Removed entirely. Genealogy is now a Selection field, not a relation.
- **`hr_recruitment` dependency**: Removed. The "Settings", "Tags", "Sources of Applicants",
  and "Activity Types" menu items under Configurations that previously pointed to
  `hr_recruitment.*` actions have been removed.
- **`bb_payin/security/security.xml`**: Was commented out in the original manifest. Groups
  (`group_payin`, `group_payin_admin`, `group_payin_edit`, `group_received_date_edit`,
  `group_verify`, `group_lock_unlock`, `group_voip_access`) are now properly loaded via
  `security/groups.xml`.

### Bug fixes applied
- **`group_registered_date_edit` → `group_received_date_edit`**: The original `bb_payin`
  `has_group()` call referenced `group_registered_date_edit` but `security.xml` defined
  `group_received_date_edit`. Fixed to use `group_received_date_edit` consistently.
- **Missing `ir.model.access` rules**: `bb.payin.sheet`, `payin.distributor`, and related
  models had no access rules in the original `bb_payin` module. Added in this module.

### `bb.payin.history` field rename
- `current_job_id` (Many2one `hr.job`) → `current_genealogy` (Selection field).
  Views and group-by contexts updated accordingly.

---

## Installation / Upgrade Steps

1. Disable (but do not uninstall) the legacy modules in dependency order.
2. Install `sales_force_support`.
3. The migration scripts in `migrations/17.0.1.0.0/` run automatically:
   - `pre-migrate.py`: copies `hr.employee` → `sf.member`, `hr.applicant` → `sf.recruit`,
     updates all FK columns, migrates config params.
   - `post-migrate.py`: renames XML IDs from legacy module names → `sales_force_support`,
     recomputes `ir.rule` records.
4. Verify data integrity:
   - `sf.member` record count matches former sales-force `hr.employee` count.
   - `sf.recruit` record count matches former `hr.applicant` count.
   - Pay-In Sheet history and all FKs intact.
   - Config parameters present under new keys.

---

## Dependencies

```python
"depends": [
    "base", "purchase", "sale",
    "documents", "web", "voip",
    "base_geolocalize",
    "bb_purchase",   # internal module
]
```

Note: `hr`, `hr_recruitment`, and all eight legacy modules listed above are **not**
dependencies of this module.
