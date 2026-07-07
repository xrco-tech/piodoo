# -*- coding: utf-8 -*-
"""Extend comm.billing.event so interactions can link into the ledger."""
from odoo import models, fields


class CommBillingEvent(models.Model):
    _inherit = 'comm.billing.event'

    interaction_id = fields.Many2one('comm.interaction', index=True,
                                      ondelete='set null')
    conversation_id = fields.Many2one('comm.conversation', index=True,
                                       ondelete='set null')
