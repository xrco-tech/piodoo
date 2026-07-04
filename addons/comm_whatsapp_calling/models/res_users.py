# -*- coding: utf-8 -*-

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # Per-user presence for inbound call routing. Away / DND agents don't
    # get the ringing popup; the webhook _send_ringing_notification skips
    # them at broadcast time so their browsers stay quiet.
    wa_call_presence = fields.Selection([
        ("available", "Available"),
        ("away",      "Away"),
        ("dnd",       "Do not disturb"),
    ], string="Call Presence", default="available",
       help="Controls whether inbound WhatsApp call notifications ring "
            "this user's browser. Set from the systray phone menu.")
