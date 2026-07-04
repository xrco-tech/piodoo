# -*- coding: utf-8 -*-

from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_whatsapp_call(self):
        """Return a client action the OWL calling service handles by
        launching the outbound-call popup with this partner's number
        pre-filled. Chooses mobile first, phone second."""
        self.ensure_one()
        to = self.mobile or self.phone or ""
        return {
            "type": "ir.actions.client",
            "tag":  "comm_whatsapp_calling.dial",
            "params": {
                "to_number":    to,
                "partner_id":   self.id,
                "partner_name": self.name or to,
            },
        }
