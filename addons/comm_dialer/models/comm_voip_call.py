# -*- coding: utf-8 -*-
from odoo import fields, models


class CommVoipCall(models.Model):
    _inherit = 'comm.voip.call'

    # Back-link so a call originated by the dialer knows its call-list row.
    dialer_contact_id = fields.Many2one(
        'comm.dialer.contact', 'Dialer Contact',
        ondelete='set null', index=True)
