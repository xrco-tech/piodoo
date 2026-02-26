{
    "name": "Sales Force Support",
    "version": "18.0.1.0.0",
    "summary": "Consolidated Sales Force management module",
    "description": """
        Consolidated module combining all Sales Force functionality:
        - Sales Force Member (sf.member) management
        - Sales Force Recruit (sf.recruit) pipeline
        - Pay-In Sheets
        - Genealogy management and remote synchronisation
        - Geographic allocation
        - Chatbot integration
        - Compuscan credit scoring integration
        - ConsumerView address verification integration
    """,
    "author": "Botle Buhle Brands",
    "website": "",
    "category": "Sales Force",
    "application": True,
    "depends": [
        "base",
        "purchase",
        "sale",
        "web",
        "voip",
        "base_geolocalize",
    ],
    "data": [
        # Security — always first
        "security/groups.xml",
        "security/ir.model.access.csv",
        "data/data.xml",
        # ── Views ──────────────────────────────────────────────────────────────
        # sf.member views first — defines sales_force_menuitem,
        # configurations_menuitem, recruitment_menuitem used by all others.
        "views/sf_member_views.xml",
        # sf.recruit — references sales_force_menuitem, recruitment_menuitem
        "views/sf_recruit_views.xml",
        # Promotion rules — references sales_force_menuitem,
        # defines promotion_menuitem_promotions used by payin_history_views
        "views/promotion_rules_views.xml",
        # ── Reports — ir.actions.report records come before views/wizards that
        #    reference them as button actions ─────────────────────────────────
        "reports/payin_report_view.xml",
        "reports/payin_report_all_view.xml",
        "reports/distributor_summary_form.xml",
        # ── Wizards — must come before payin_views as menus reference their
        #    actions: action_payin_sheet_wizard, action_active_status_config_wizard
        "wizards/payin_wizard_view.xml",
        "wizards/payin_report_wizard.xml",
        "wizards/capture.xml",
        "wizards/consultant_move_wizard_view.xml",
        "wizards/consultant_promote_wizard_view.xml",
        "wizards/consultant_blacklist_wizard_view.xml",
        "wizards/consultant_create_wizard_view.xml",
        "wizards/display_created_consultant.xml",
        "wizards/consultant_search_view.xml",
        "wizards/partner_consumerview_resolve_views.xml",
        # ── Pay-In views ───────────────────────────────────────────────────────
        "views/payin_history_views.xml",
        "views/payin_views.xml",
        # ── Inherited model views ───────────────────────────────────────────────
        "views/res_partner_views.xml",
        "views/res_country_views.xml",
        "views/res_company_views.xml",
        "views/res_config_settings_views.xml",
        "views/res_users_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # CSS
            "sales_force_support/static/src/css/kanban_ribbon.css",
            "sales_force_support/static/src/css/payin.css",
            "sales_force_support/static/src/css/tree_header.css",
            # JS — partner & VOIP (from botle_buhle_custom)
            "sales_force_support/static/src/js/partner_controller.js",
            "sales_force_support/static/src/js/voip_recruit_popup.js",
            # JS — pay-in sheets (from bb_payin)
            "sales_force_support/static/src/js/timer.js",
            "sales_force_support/static/src/js/timesheet_uom.js",
            "sales_force_support/static/src/js/payin.js",
            "sales_force_support/static/src/js/payin_sheet_create_wizard.js",
            "sales_force_support/static/src/js/payin_sheet_group_access_right.js",
            "sales_force_support/static/src/js/payin_sheet_line_event_listener.js",
            "sales_force_support/static/src/js/payin_sheet_pdf_download_listener.js",
            "sales_force_support/static/src/js/payin_sheets_enquiry.js",
            "sales_force_support/static/src/js/action_manager_payin_sheet_report_dl.js",
            "sales_force_support/static/src/js/action_manager_xlsx.js",
            "sales_force_support/static/src/js/datepicker.js",
            "sales_force_support/static/src/js/group_expand.js",
            "sales_force_support/static/src/js/promotions_controller.js",
            "sales_force_support/static/src/js/systray_voip_access.js",
            # OWL/QWeb templates
            "sales_force_support/static/src/xml/timer.xml",
            "sales_force_support/static/src/xml/dialing_panel.xml",
            "sales_force_support/static/src/xml/expand_buttons.xml",
            "sales_force_support/static/src/xml/payin_sheet_enquiry_report.xml",
            "sales_force_support/static/src/xml/voip_phonecall_details.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
