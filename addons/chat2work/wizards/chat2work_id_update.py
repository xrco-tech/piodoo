# -*- coding: utf-8 -*-
"""Lets an agent add or correct a candidate's SA ID number, with a reason."""

from odoo import fields, models


class Chat2workIdUpdate(models.TransientModel):
    _name = 'chat2work.id.update'
    _description = 'Update a Candidate ID Number'

    candidate_id = fields.Many2one('chat2work.candidate', required=True, ondelete='cascade')
    current_id = fields.Char('Current ID Number', related='candidate_id.id_number_masked')
    id_number = fields.Char('New ID Number', required=True)
    reason = fields.Char(required=True, help="Why it's changing. This goes in the chatter.")

    def action_save(self):
        self.ensure_one()
        self.candidate_id._c2w_change_id_number(self.id_number, self.reason)
        # This table holds the number unencrypted, so don't leave it for the vacuum.
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}
