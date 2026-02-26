# Custom model definitions

# ── Core entities (must be imported first — other models reference them) ──────
from . import sf_recruit_stage           # sf.recruit.stage
from . import sf_member                  # sf.member (replaces hr.employee)
from . import sf_recruit                 # sf.recruit + required.field.state (replaces hr.applicant)

# ── Source: bbb_sales_force_genealogy ─────────────────────────────────────────
from . import sf_distribution           # sf.mapping.field, user.otp
from . import interview_decline_reasons  # interview.decline.reasons

# Source: botle_buhle_custom
from . import status_audit_trail         # status.audit.trail
from . import res_communication          # res.communication
from . import hr_contacts                # hr.contacts
from . import res_vetting                # res.vetting
from . import promotion_rules            # promotion.rules, promotion.rules.months

# Source: bb_payin
from . import bb_payin_sheet             # bb.payin.sheet, bb.payin.sheet.line, payin.distributor, payin.distributor.line, payin.capture.time, payin.distributor.capture.time
from . import bb_payin_history           # bb.payin.history
from . import bb_payin_sheets_report     # bb.payin.sheets.enquiry.report
from . import bb_payin_report_tracker    # captured.payinsheet.report.track, captured.summary.report.track
