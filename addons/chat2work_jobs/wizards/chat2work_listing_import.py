# -*- coding: utf-8 -*-
import base64

from odoo import fields, models


class Chat2workListingImport(models.TransientModel):
    _name = 'chat2work.listing.import'
    _description = 'Import Chat2Work Job Listings'

    source_id = fields.Many2one('chat2work.listing.source', required=True,
                                default=lambda self: self.env.ref('chat2work_jobs.listing_source_manual', False))
    file = fields.Binary('CSV File', required=True)
    filename = fields.Char()
    close_missing = fields.Boolean('Close listings not in this file',
                                   help="Use when the file holds everything currently open for this source.")
    result = fields.Char(readonly=True)

    def action_import(self):
        self.ensure_one()
        self.result = self.source_id._import_csv(base64.b64decode(self.file), close_missing=self.close_missing)
        self.env['chat2work.listing'].search([('source_id', '=', self.source_id.id), ('state', '=', 'open')]).action_suggest_candidates()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}
