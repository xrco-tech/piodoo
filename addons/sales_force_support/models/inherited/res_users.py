# -*- coding: utf-8 -*-
# Sources merged:
#   bb_payin/models/res_users.py   (update_sip_ignore_incoming)
#   bb_chatbot/models/res_users.py (chatbot_access_token + generate_chatbot_access_token)
import binascii
import hashlib
import os

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    # ── Chatbot access token ──────────────────────────────────────────────────
    chatbot_access_token = fields.Char(
        group="base.group_system", string="Chatbot Access Token"
    )

    def generate_chatbot_access_token(self):
        # XXX: NEVER call this method from your own code as it contains a cursor commit

        self.ensure_one()

        token = binascii.hexlify(os.urandom(16))
        hashed_token = hashlib.sha512(token)

        self.chatbot_access_token = hashed_token.hexdigest()
        self.env.cr.commit()

        raise UserError(
            _(
                "Keep your token safe as it cannot be retrieved and must be "
                "regenerated if lost:\n\n%s"
            )
            % token.decode("utf-8")
        )

