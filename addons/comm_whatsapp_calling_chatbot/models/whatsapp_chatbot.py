# -*- coding: utf-8 -*-

from odoo import fields, models


class WhatsAppChatbot(models.Model):
    _inherit = "whatsapp.chatbot"

    call_log_count = fields.Integer(
        compute="_compute_call_log_count",
        help="How many whatsapp.call.log records were dialled from this "
             "voice-channel chatbot's Agent Workspace.",
    )

    def _compute_call_log_count(self):
        Log = self.env["whatsapp.call.log"]
        for rec in self:
            rec.call_log_count = Log.search_count(
                [("chatbot_id", "=", rec.id)]
            )

    def action_view_call_logs(self):
        """Open the call log list filtered to this chatbot."""
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "name":      f"Calls — {self.name}",
            "res_model": "whatsapp.call.log",
            "view_mode": "list,form",
            "domain":    [("chatbot_id", "=", self.id)],
            "context":   {"default_chatbot_id": self.id},
        }
