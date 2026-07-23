# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Meta's business-scoped user ID (e.g. "US.13491208655302741918") —
    # rolling out alongside optional WhatsApp usernames. Phone number
    # (mobile/phone) stays the authoritative identity for now; this is
    # captured in parallel wherever a partner is matched/created from a
    # WhatsApp webhook, so identity isn't lost once phone-number fields
    # start getting omitted from webhooks for users who've adopted a
    # username and gone quiet for 30+ days.
    # See: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
    wa_bsuid = fields.Char(
        string="WhatsApp Business-Scoped User ID", index=True,
        help="Meta's business-scoped user ID for this contact, when known.",
    )

    @api.model
    def _handle_wa_bsuid_rotation(self, previous_bsuid, current_bsuid):
        """Meta can rotate a user's BSUID and fires a user_id_update
        webhook with {previous, current} when it does — without this,
        a stored wa_bsuid silently goes stale and a later send targeting
        it just fails. Re-points every partner still on the old value."""
        if not previous_bsuid or not current_bsuid or previous_bsuid == current_bsuid:
            return
        stale = self.sudo().search([("wa_bsuid", "=", previous_bsuid)])
        if stale:
            stale.write({"wa_bsuid": current_bsuid})
