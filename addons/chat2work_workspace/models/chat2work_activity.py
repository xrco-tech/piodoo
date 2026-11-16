# -*- coding: utf-8 -*-
"""What Chat2Work agents do, noted for the Team report (comm_agent_activity).

A line is written when an agent checks a job, decides a match, checks or joins
an employer, or sends a message. The report asks this file who the agents are
and what is waiting."""
from datetime import timedelta

from odoo import api, fields, models

from .chat2work_employers import TO_CHECK
from .chat2work_workspace import REPLY_CHANNELS

SOURCE = 'chat2work'


class Chat2workListing(models.Model):
    _inherit = 'chat2work.listing'

    def _set_verification(self, state):
        changed = super()._set_verification(state)
        Log = self.env['comm.agent.activity']
        if changed and Log._counts():
            labels = dict(self._fields['verification_state']._description_selection(self.env))
            for listing in changed:
                Log._reverse('job_check', listing, state)
                if state != 'unverified':
                    Log._log('job_check', SOURCE, listing, name=listing.title, result=state,
                             label=labels.get(state), has_note=bool(listing.verification_note))
        return changed


class Chat2workListingMatch(models.Model):
    _inherit = 'chat2work.listing.match'

    def _c2w_activity(self, state, label):
        Log = self.env['comm.agent.activity']
        if Log._counts():
            for match in self:
                Log._reverse('match', match, state)
                Log._log('match', SOURCE, match, name=match.listing_id.title, result=state, label=label)

    def action_approve(self):
        res = super().action_approve()
        self._c2w_activity('approved', self.env._("Approved"))
        return res

    def action_reject(self):
        res = super().action_reject()
        self._c2w_activity('rejected', self.env._("Rejected"))
        return res


class Chat2workWorkspaceActivity(models.AbstractModel):
    _inherit = 'chat2work.workspace'

    @api.model
    def _activity_waiting(self, candidate):
        """Seconds since the oldest message of theirs that nothing has answered yet, or None."""
        if not candidate.partner_id:
            return None
        self.env['comm.interaction'].flush_model()
        self.env.cr.execute("""
            SELECT i.at, i.direction
              FROM comm_interaction i
              JOIN comm_conversation c ON c.id = i.conversation_id
              JOIN comm_channel ch ON ch.id = i.channel_id
             WHERE c.partner_id = %s AND ch.code IN %s AND COALESCE(i.status, '') <> 'failed'
             ORDER BY i.at DESC, i.id DESC
             LIMIT 50
        """, [candidate.partner_id.id, REPLY_CHANNELS])
        oldest = None
        for at, direction in self.env.cr.fetchall():
            if direction != 'inbound':
                break
            oldest = at
        return (fields.Datetime.now() - oldest).total_seconds() if oldest else None

    @api.model
    def ws_send(self, candidate_id, text, channel=None):
        candidate = self.env['chat2work.candidate'].browse(candidate_id).exists()
        wait = self._activity_waiting(candidate) if candidate else None
        res = super().ws_send(candidate_id, text, channel=channel)
        self.env['comm.agent.activity']._log('reply' if wait else 'outreach', SOURCE, candidate, wait=wait)
        return res

    @api.model
    def ws_unknown_send(self, wa_id, text):
        res = super().ws_unknown_send(wa_id, text)
        if res and (text or '').strip():
            self.env['comm.agent.activity']._log('reply', SOURCE, name=self.env._("A number that is not a candidate"))
        return res

    @api.model
    def ws_employer_save(self, employer_id, values=None, state=None):
        res = super().ws_employer_save(employer_id, values=values, state=state)
        if state:
            employer = self._employer(employer_id)
            Log = self.env['comm.agent.activity']
            Log._reverse('employer_check', employer, employer.state)
            Log._log('employer_check', SOURCE, employer, result=employer.state,
                     label=self._label(employer, 'state'), has_note=bool((employer.note or '').strip()))
        return res

    @api.model
    def ws_employer_join(self, employer_id, other_id):
        other = self._employer(other_id).name
        res = super().ws_employer_join(employer_id, other_id)
        employer = self._employer(employer_id)
        self.env['comm.agent.activity']._log(
            'employer_join', SOURCE, employer, label=self.env._("Joined with %s", other))
        return res


class CommAgentActivityReport(models.AbstractModel):
    _inherit = 'comm.agent.activity.report'

    @api.model
    def _sources(self):
        return super()._sources() + [(SOURCE, 'Chat2Work')]

    @api.model
    def _agents(self, source):
        users = super()._agents(source)
        if source in (SOURCE, 'both'):
            group = self.env.ref('chat2work.group_agent', raise_if_not_found=False)
            if group:
                users |= group.sudo().users.filtered(lambda user: user.active and not user.share)
        return users

    @api.model
    def _backlog(self, source):
        rows = super()._backlog(source)
        if source not in (SOURCE, 'both'):
            return rows
        week = fields.Datetime.now() - timedelta(days=7)
        Employer = self.env['chat2work.employer'].sudo()
        Listing = self.env['chat2work.listing'].sudo()
        done = lambda action: self.env['comm.agent.activity'].sudo().search_count(
            [('action', '=', action), ('at', '>=', week)])
        return rows + [{
            'key': 'employers',
            'label': self.env._("employers waiting to be checked"),
            'waiting': Employer.search_count([('state', 'in', TO_CHECK), ('listing_ids.state', '=', 'open')]),
            'done': done('employer_check'),
            'new': Employer.search_count([('create_date', '>=', week), ('listing_ids.state', '=', 'open')]),
            'action': 'employer_check',
        }, {
            'key': 'jobs',
            'label': self.env._("jobs waiting to be verified"),
            'waiting': Listing.search_count([('work_state', '=', 'to_verify')]),
            'done': done('job_check'),
            'new': Listing.search_count([('create_date', '>=', week)]),
            'action': 'job_check',
        }]
