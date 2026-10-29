# -*- coding: utf-8 -*-
"""Retention (terms §6): a candidate's data is kept for 12 months after they
were last active, or deleted sooner on request.

"Active" = a USSD or WhatsApp session, a CV upload or build, or a CV help
request. A daily cron erases candidates inactive for chat2work.retention_months
(default 12); admins can erase one at once from the candidate form.
"""

import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .chat2work_cv import _commit
from .chat2work_ussd import msisdn_variants

_logger = logging.getLogger(__name__)

RETENTION_MONTHS = 12


class Chat2workCandidateRetention(models.Model):
    _inherit = 'chat2work.candidate'

    last_active_at = fields.Datetime('Last Active', default=fields.Datetime.now, readonly=True, index=True,
                                     help="Data is deleted %d months after this." % RETENTION_MONTHS)

    def _c2w_touch(self):
        self.sudo().write({'last_active_at': fields.Datetime.now()})

    def _c2w_erase_extra(self):
        """Hook for modules holding more of the candidate's data (chat2work_ucx)."""

    def _c2w_erase(self):
        """Delete the candidate and everything Chat2Work holds about them."""
        for rec in self.sudo().with_context(active_test=False):
            phones = msisdn_variants(rec.phone) if rec.phone else []
            domain = [('candidate_id', '=', rec.id)]
            if phones:
                domain = ['|', ('phone', 'in', phones)] + domain
            self.env['chat2work.callback.request'].sudo().search(domain).unlink()
            self.env['ir.attachment'].sudo().search([
                ('res_model', '=', rec._name), ('res_id', '=', rec.id)]).unlink()
            rec._c2w_erase_extra()
            _logger.info("chat2work: erased candidate %s", rec.id)
            rec.unlink()

    def action_c2w_erase(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only administrators can delete candidate data."))
        self._c2w_erase()
        return {'type': 'ir.actions.act_window', 'res_model': self._name,
                'view_mode': 'list,form', 'name': _('Candidates'), 'target': 'main'}

    @api.model
    def _cron_purge_inactive(self):
        months = int(self.env['ir.config_parameter'].sudo().get_param(
            'chat2work.retention_months', RETENTION_MONTHS))
        cutoff = fields.Datetime.now() - relativedelta(months=months)
        stale = self.sudo().with_context(active_test=False).search(
            [('last_active_at', '<', cutoff)], limit=500)
        for rec in stale:
            rec._c2w_erase()
            _commit(self.env)
        if stale:
            _logger.info("chat2work: erased %d candidates inactive for %d months", len(stale), months)
