# -*- coding: utf-8 -*-
# Sources: partner_compuscan/models/res_company.py
#          partner_consumerview/models/res_company.py
from odoo import models, fields, _
from odoo.exceptions import RedirectWarning, UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    # ── Compuscan ────────────────────────────────────────────────────────────
    compuscan_user = fields.Char(string="Compuscan Username")
    compuscan_pass = fields.Char(string="Compuscan Password")
    compuscan_env = fields.Selection(
        [("test", "Testing"), ("prod", "Production")],
        default="test",
        required=True,
        string="Compuscan Environment",
    )

    def _get_compuscan_credentials(self):
        self.ensure_one()

        if not self.compuscan_user or not self.compuscan_pass:
            if self.env.user.has_group("base.group_system"):
                action = self.env.ref("base.action_res_company_form")
                raise RedirectWarning(
                    _("Compuscan credentials not configured"),
                    action.id,
                    _("Open Configuration"),
                )
            else:
                raise UserError(
                    _("Compuscan credentials not configured. Contact your administrator.")
                )

        return self.compuscan_user, self.compuscan_pass

    # ── ConsumerView ─────────────────────────────────────────────────────────
    consumerview_user = fields.Char(string="ConsumerView Username")
    consumerview_pass = fields.Char(string="ConsumerView Password")
    consumerview_env = fields.Selection(
        [("test", "Testing"), ("prod", "Production")],
        default="test",
        required=True,
        string="ConsumerView Environment",
    )

    def _get_consumerview_credentials(self):
        self.ensure_one()

        if not self.consumerview_user or not self.consumerview_pass:
            if self.env.user.has_group("base.group_system"):
                action = self.env.ref("base.action_res_company_form")
                raise RedirectWarning(
                    _("ConsumerView credentials not configured"),
                    action.id,
                    _("Open Configuration"),
                )
            else:
                raise UserError(
                    _(
                        "ConsumerView credentials not configured. Contact your administrator."
                    )
                )

        return self.consumerview_user, self.consumerview_pass
