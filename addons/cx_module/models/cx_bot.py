# -*- coding: utf-8 -*-
from odoo import models


class CommBot(models.Model):
    _inherit = 'comm.bot'

    def action_cx_open_flow_canvas(self):
        """Open the UCX flow canvas for this bot (Phase 2 flow-builder)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'cx_module_bot_flow',
            'name': 'Flow: %s' % (self.name or ''),
            'params': {'bot_id': self.id, 'bot_name': self.name or ''},
        }
