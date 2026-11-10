# -*- coding: utf-8 -*-
"""Tell open workspaces that something changed, so they reload themselves.

The notice says nothing about who or what: any signed-in user can listen on a
named bus channel, so it carries no candidate details. The workspace then asks
for the data through its own agent-only calls.
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

BUS_CHANNEL = 'chat2work_workspace'
BUS_TYPE = 'chat2work_workspace/changed'


def _notify(env, what):
    try:
        env['bus.bus']._sendone(BUS_CHANNEL, BUS_TYPE, {'what': what})
    except Exception:  # the screen also reloads on a timer; never block the write
        _logger.debug("chat2work_workspace: live notice skipped", exc_info=True)


class CommInteractionWorkspace(models.Model):
    _inherit = 'comm.interaction'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        partners = records.sudo().conversation_id.partner_id
        if partners and self.env['chat2work.candidate'].sudo().search_count(
                [('partner_id', 'in', partners.ids)], limit=1):
            _notify(self.env, 'timeline')
        return records


class Chat2workCallbackWorkspace(models.Model):
    _inherit = 'chat2work.callback.request'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _notify(self.env, 'callback')
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            _notify(self.env, 'callback')
        return res


class Chat2workCandidateWorkspace(models.Model):
    _inherit = 'chat2work.candidate'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _notify(self.env, 'candidate')
        return records
