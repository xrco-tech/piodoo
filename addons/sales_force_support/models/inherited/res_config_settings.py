# -*- coding: utf-8 -*-
# Sources merged:
#   bbb_sales_force_genealogy/models/res_config_settings.py  (sync params)
#   botle_buhle_custom/models/res_config_settings.py         (WhatsApp params)
#   bb_payin/models/res_config_settings.py                   (Telviva / payin params)
#   partner_consumerview/models/res_config_settings.py       (ConsumerView helper)
# All config_parameter keys re-namespaced from legacy prefixes → sales_force_support.*
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # ── Outbound / Inbound Synchronisation ───────────────────────────────────
    enable_outbound_synchronisation = fields.Boolean(
        string="Enable Outbound Synchronisation",
        config_parameter="sales_force_support.enable_outbound_synchronisation",
        default=False,
        help="Enables the outbound synchronisation of Sales Force data with a remote instance.",
    )
    enable_inbound_synchronisation = fields.Boolean(
        string="Enable Inbound Synchronisation",
        config_parameter="sales_force_support.enable_inbound_synchronisation",
        default=False,
        help="Enables the inbound synchronisation of Sales Force data with a remote instance.",
    )
    outbound_url = fields.Char(
        string="Outbound URL",
        config_parameter="sales_force_support.outbound_url",
        help="The URL of the outbound/remote synchronisation API endpoint.",
    )
    outbound_database = fields.Char(
        string="Outbound Database Name",
        config_parameter="sales_force_support.outbound_database",
    )
    outbound_login = fields.Char(
        string="Outbound Database Login Email",
        config_parameter="sales_force_support.outbound_login",
    )
    outbound_password = fields.Char(
        string="Outbound Login Password",
        config_parameter="sales_force_support.outbound_password",
    )

    # ── WhatsApp (BBBot sender) ───────────────────────────────────────────────
    whatsapp_bbbot_sender_token = fields.Char(
        string="WhatsApp BBBot Sender Token",
        config_parameter="sales_force_support.whatsapp_bbbot_sender_token",
    )
    whatsapp_bbbot_sender_namespace = fields.Char(
        string="WhatsApp BBBot Sender Namespace",
        config_parameter="sales_force_support.whatsapp_bbbot_sender_namespace",
    )
    whatsapp_bbbot_sender_phone_number_id = fields.Char(
        string="WhatsApp BBBot Sender Phone Number ID",
        config_parameter="sales_force_support.whatsapp_bbbot_sender_phone_number_id",
    )

    # ── Pay-In / Telviva ─────────────────────────────────────────────────────
    report_print_count = fields.Integer(
        string="Report Print Count",
        default=1,
        config_parameter="sales_force_support.report_print_count",
    )
    payin_active_status_reference_date = fields.Char(
        string="Active Status Reference Date",
        config_parameter="sales_force_support.payin_active_status_reference_date",
    )
    telviva_username = fields.Char(
        string="Telviva Username",
        config_parameter="sales_force_support.telviva_username",
    )
    telviva_password = fields.Char(
        string="Telviva Password",
        config_parameter="sales_force_support.telviva_password",
    )
    telviva_start_time = fields.Char(
        string="Telviva Start Time",
        config_parameter="sales_force_support.telviva_start_time",
        help="Unix timestamp of starting time.",
    )
    telviva_end_time = fields.Char(
        string="Telviva End Time",
        config_parameter="sales_force_support.telviva_end_time",
        help="Unix timestamp of ending time.",
    )
    telviva_duration_min = fields.Char(
        string="Telviva Min Duration",
        config_parameter="sales_force_support.telviva_duration_min",
        help="Minimum duration in seconds.",
    )
    telviva_duration_max = fields.Char(
        string="Telviva Max Duration",
        config_parameter="sales_force_support.telviva_duration_max",
        help="Maximum duration in seconds.",
    )
    telviva_recordgroup = fields.Char(
        string="Telviva Record Group",
        config_parameter="sales_force_support.telviva_recordgroup",
        help="ID of record group. 0 for all groups.",
    )

    # ── ConsumerView helper ───────────────────────────────────────────────────
    def button_consumerview_open(self):
        return self.env.ref("base.action_view_partner_form")
