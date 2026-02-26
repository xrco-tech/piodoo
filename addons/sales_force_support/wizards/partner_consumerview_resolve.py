# -*- coding: utf-8 -*-
# Source: partner_consumerview/wizards/partner_consumerview_resolve.py

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PartnerConsumerViewResolve(models.TransientModel):
    _name = "partner.consumerview.resolve"
    _description = "Partner ConsumerView Resolve"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", string="Partner"
    )
    ref = fields.Char(string="ConsumerView Reference")

    chosen_line_id = fields.Many2one(
        "partner.consumerview.resolve.line",
        ondelete="set null",
        string="Resolution Choice",
    )
    line_ids = fields.One2many(
        "partner.consumerview.resolve.line", "resolve_id", string="Resolution Lines"
    )

    def action_choose(self):
        self.ensure_one()

        if not self.chosen_line_id:
            raise ValidationError(_("You must make a selection"))

        #         if not self.env.user.has_group('partner_consumerview.group_consumerview_operator'):
        #             self.check_access_rights('write', raise_exception=True)

        self.partner_id.write(
            {
                "name": self.chosen_line_id.name,
                "first_name": self.chosen_line_id.first_name,
                "last_name": self.chosen_line_id.last_name,
                "street": self.chosen_line_id.street,
                "street2": self.chosen_line_id.street2,
                "suburb": self.chosen_line_id.suburb,
                "city": self.chosen_line_id.city,
                "state_id": self.chosen_line_id.state_id.id,
                "country_id": self.chosen_line_id.state_id.country_id.id,
                "zip": self.chosen_line_id.zip,
                "consumerview_ref": self.ref,
            }
        )

        body = "<p>Data populated from ConsumerView:</p>\n"
        body += "<ul>\n\t<li><strong>Name:</strong> %s</li>\n" % (
            self.chosen_line_id.name,
        )
        body += "\t<li><strong>Street:</strong> %s</li>\n" % (
            self.chosen_line_id.street,
        )
        if self.chosen_line_id.street2:
            body += "\t<li>%s</li>\n" % (self.chosen_line_id.street2,)
        body += "\t<li><strong>Suburb:</strong> %s</li>\n" % (
            self.chosen_line_id.suburb,
        )
        body += "\t<li><strong>City:</strong> %s</li>\n" % (self.chosen_line_id.city,)
        body += "\t<li><strong>Postcode:</strong> %s</li>\n" % (
            self.chosen_line_id.zip,
        )
        body += "\t<li><strong>Province:</strong> %s</li>\n" % (
            self.chosen_line_id.state_id.name,
        )
        body += "\t<li><strong>Country:</strong> %s</li>\n" % (
            self.chosen_line_id.state_id.country_id.name,
        )
        body += "\t<li><strong>ConsumerView Reference:</strong> %s</li>\n" % (self.ref,)
        body += "</ul>"
        if len(self.line_ids) > 1:
            body += (
                "\n<em>There were %d other results returned from ConsumerView.</em>"
                % (len(self.chosen_line_ids),)
            )
        if not self.env.company.consumerview_env == "prod":
            body += "\n<em>This request was executed with the sandbox environment.</em>"

        self.partner_id.message_post(
            body=body,
            body_is_html=True,
        )


class PartnerConsumerViewResolveLine(models.TransientModel):
    _name = "partner.consumerview.resolve.line"
    _description = "Partner ConsumerView Resolve Line"

    resolve_id = fields.Many2one(
        "partner.consumerview.resolve",
        required=True,
        ondelete="cascade",
        string="Resolution",
    )

    name = fields.Char(string="Name")
    first_name = fields.Char(string="First Name")
    last_name = fields.Char(string="Surname")
    street = fields.Char(string="Street")
    street2 = fields.Char(string="Street2")
    suburb = fields.Char(string="Suburb")
    city = fields.Char(string="City")
    zip = fields.Char(string="Postcode")

    state_id = fields.Many2one(
        "res.country.state", ondelete="cascade", string="Province"
    )

    opt_out = fields.Boolean(string="Opt Out")

    # Applified Developer : Comment Start, For old code => Issue #Universal, name_get() no longer supported
    # def name_get(self):
    #     res = []
    #     for record in self:
    #         street2 = record.street2 and '%s, %s' % (record.street2, record.suburb) or record.suburb
    #         names = [record.name, record.street, street2, record.city, record.state_id.name, record.zip]
    #         res.append((record.id, ', '.join(names)))
    #     return res
    # Applified Developer : Comment End, For old code

    # Applified Developer : Comment Start, For new code => Issue #Universal, name_get() no longer supported
    def _compute_display_name(self):
        for record in self:
            street2 = (
                record.street2
                and "%s, %s" % (record.street2, record.suburb)
                or record.suburb
            )
            names = [
                record.name,
                record.street,
                street2,
                record.city,
                record.state_id.name,
                record.zip,
            ]
            record.display_name = f"{record.id}, {', '.join(names)}"

    # Applified Developer : Comment End, For new code
