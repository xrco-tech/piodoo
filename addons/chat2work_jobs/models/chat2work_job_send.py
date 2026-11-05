# -*- coding: utf-8 -*-
"""Agents reviewing a candidate's job matches and sending them from the candidate.

The hourly alert sends Good matches on its own. From the candidate an agent can
also send them straight away and pick the channel. We recommend one from how
the candidate has engaged with us so far: messages they've sent us on WhatsApp,
whether they read ours, and how they signed up.
"""

import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

CHANNELS = [('whatsapp', 'WhatsApp'), ('sms', 'SMS')]
HISTORY = timedelta(days=60)


class Chat2workCandidateJobSend(models.Model):
    _inherit = 'chat2work.candidate'

    job_match_review_count = fields.Integer('Matches to Review', compute='_compute_job_match_counts')
    job_match_ready_count = fields.Integer('Matches to Send', compute='_compute_job_match_counts')

    @api.depends('listing_match_ids.state', 'listing_match_ids.notify_state', 'listing_match_ids.listing_id.state')
    def _compute_job_match_counts(self):
        for rec in self:
            matches = rec.listing_match_ids.filtered(lambda m: m.listing_id.state == 'open')
            rec.job_match_review_count = len(matches.filtered(lambda m: m.state == 'suggested'))
            rec.job_match_ready_count = len(matches._c2w_to_send())

    def _c2w_recommended_channel(self):
        """('whatsapp' or 'sms', why) from their engagement history."""
        self.ensure_one()
        if not self.whatsapp_opt_in:
            return 'sms', "Doesn't use WhatsApp with us"
        Message = self.env['whatsapp.message'].sudo()
        wa_id = re.sub(r'\D', '', self.phone or '')
        since = fields.Datetime.now() - HISTORY
        last_in = Message.search([('wa_id', '=', wa_id), ('is_incoming', '=', True)],
                                 order='message_timestamp desc', limit=1)
        if self._c2w_wa_window_open():
            return 'whatsapp', "Messaged us on WhatsApp in the last 24 hours"
        if last_in and last_in.message_timestamp and last_in.message_timestamp >= since:
            return 'whatsapp', "Last messaged us on WhatsApp on %s" % last_in.message_timestamp.strftime('%d %b')
        ours = Message.search([('wa_id', '=', wa_id), ('is_incoming', '=', False), ('create_date', '>=', since)])
        statuses = set(ours.mapped('message_status'))
        if 'read' in statuses:
            return 'whatsapp', "Reads our WhatsApp messages"
        if ours and statuses <= {'failed', False}:
            return 'sms', "Our WhatsApp messages to them didn't go through"
        if ours:
            return 'sms', "Hasn't read our last %d WhatsApp message%s" % (len(ours), '' if len(ours) == 1 else 's')
        if (self.registered_via or '').lower() == 'ussd':
            return 'sms', "Signed up on USSD and hasn't used WhatsApp with us yet"
        return 'whatsapp', "Uses WhatsApp"

    def action_c2w_send_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Jobs to %s' % self.name,
            'res_model': 'chat2work.job.send',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }


class Chat2workListingMatchSend(models.Model):
    _inherit = 'chat2work.listing.match'

    listing_verification = fields.Selection(related='listing_id.verification_state', string='Listing Checked')

    def _c2w_to_send(self):
        """Good matches on open listings the candidate hasn't been told about."""
        return self.filtered(lambda m: m.state == 'approved' and m.notify_state != 'sent'
                             and m.listing_id.state == 'open')


class Chat2workJobSend(models.TransientModel):
    _name = 'chat2work.job.send'
    _description = 'Chat2Work: send job matches to a candidate'

    candidate_id = fields.Many2one('chat2work.candidate', required=True, readonly=True)
    match_ids = fields.Many2many('chat2work.listing.match', string='Jobs to Send',
                                 domain="[('candidate_id', '=', candidate_id), ('state', '=', 'approved'), "
                                        "('listing_state', '=', 'open')]")
    channel = fields.Selection(CHANNELS, required=True)
    recommended_channel = fields.Selection(CHANNELS, readonly=True)
    recommendation = fields.Char('Why', readonly=True)
    whatsapp_available = fields.Boolean(related='candidate_id.whatsapp_opt_in')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        candidate = self.env['chat2work.candidate'].browse(vals.get('candidate_id'))
        if candidate:
            channel, why = candidate._c2w_recommended_channel()
            vals.update(channel=channel, recommended_channel=channel, recommendation=why,
                        match_ids=[(6, 0, candidate.listing_match_ids._c2w_to_send().ids)])
        return vals

    def action_send(self):
        self.ensure_one()
        candidate, matches = self.candidate_id, self.match_ids
        if not matches:
            raise UserError("Pick at least one Good match to send.")
        if self.channel == 'whatsapp' and not candidate.whatsapp_opt_in:
            raise UserError("%s doesn't use WhatsApp with us. Send it by SMS." % candidate.name)
        if not candidate._c2w_send_job_alert(matches, channel=self.channel):
            raise UserError("The %s message didn't go through. Try %s instead." % (
                dict(CHANNELS)[self.channel], 'SMS' if self.channel == 'whatsapp' else 'WhatsApp'))
        now = fields.Datetime.now()
        matches.sudo().write({'notify_state': 'sent', 'notified_at': now})
        candidate.sudo().job_alert_at = now
        candidate.message_post(body="Sent %d job%s by %s: %s" % (
            len(matches), '' if len(matches) == 1 else 's', dict(CHANNELS)[self.channel],
            ', '.join(m._c2w_label() for m in matches)))
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'success', 'message': 'Jobs sent to %s by %s.' % (candidate.name, dict(CHANNELS)[self.channel]),
            'next': {'type': 'ir.actions.act_window_close'}}}
