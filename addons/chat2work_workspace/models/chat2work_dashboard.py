# -*- coding: utf-8 -*-
"""The numbers on the Chat2Work dashboard, in one call.

Agents only, like the workspace. Days are the user's own: "today" starts at
their midnight. Nothing here writes."""

from datetime import datetime, time, timedelta
from statistics import median

import pytz

from odoo import _, api, fields, models

from .chat2work_workspace import CV_DONE, OPEN_CALLBACK, REPLY_CHANNELS, _dt

PERIODS = {'today': 0, '7d': 6, '30d': 29}
CHART_DAYS = 14
QUICK = 15 * 60                         # "answered within 15 minutes"
JOBS_TO_CHECK = ('to_verify', 'to_review')
PROCESSES = ('signup', 'update', 'callback')      # sessions that ended with something done
FLOW_CHANNELS = ('ussd', 'whatsapp')


class Chat2workWorkspace(models.AbstractModel):
    _inherit = 'chat2work.workspace'

    # ── Time ─────────────────────────────────────────────────────────────
    @api.model
    def _dash_tz(self):
        try:
            return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    @api.model
    def _dash_start(self, tz, days_back):
        """The user's midnight `days_back` days ago, as the UTC time the database keeps."""
        today = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).date()
        local = tz.localize(datetime.combine(today - timedelta(days=days_back), time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    # ── The pieces ───────────────────────────────────────────────────────
    @api.model
    def _dash_todo(self):
        waiting = self._waiting_replies()
        Callback = self.env['chat2work.callback.request']
        callbacks = Callback.search([('state', 'in', OPEN_CALLBACK), ('candidate_id', '!=', False)], order='create_date')
        Listing = self.env['chat2work.listing']
        unknown = [row for row in self._unknown_latest() if row['needs_reply']]
        todo = {
            'reply': len(waiting),
            'reply_since': _dt(min((row[2] for row in waiting), default=False)),
            'callbacks': len(callbacks),
            'callbacks_new': len(callbacks.filtered(lambda c: c.state == 'new')),
            'callback_since': _dt(callbacks[:1].create_date),
            'jobs_verify': Listing.search_count([('work_state', '=', 'to_verify')]),
            'jobs_review': Listing.search_count([('work_state', '=', 'to_review')]),
            'unknown': len(unknown),
            'id_open': False,
            'id_failed': False,
        }
        if self._can_id_check():
            Candidate = self.env['chat2work.candidate']
            todo['id_open'] = Candidate.search_count(self._list_domain('id_open'))
            todo['id_failed'] = Candidate.search_count(self._list_domain('id_failed'))
        return todo

    @api.model
    def _dash_new_candidates(self, tz, since):
        """One bar per day for the last 14 days, by how they signed up, and the period's total."""
        Candidate = self.env['chat2work.candidate'].with_context(active_test=False)
        chart_start = self._dash_start(tz, CHART_DAYS - 1)
        first_day = pytz.utc.localize(chart_start).astimezone(tz).date()
        days = [{'date': fields.Date.to_string(first_day + timedelta(days=i)), 'whatsapp': 0, 'ussd': 0, 'other': 0}
                for i in range(CHART_DAYS)]
        total = 0
        for row in Candidate.search_read([('create_date', '>=', min(chart_start, since))], ['create_date', 'registered_via']):
            via = (row['registered_via'] or '').lower()
            via = via if via in ('whatsapp', 'ussd') else 'other'
            index = (pytz.utc.localize(row['create_date']).astimezone(tz).date() - first_day).days
            if 0 <= index < CHART_DAYS:
                days[index][via] += 1
            total += row['create_date'] >= since
        return {'days': days, 'total': total, 'all': Candidate.search_count([('active', '=', True)])}

    @api.model
    def _dash_replies(self, since):
        """How long candidates waited for a reply on WhatsApp or SMS since `since`.

        A wait starts with a candidate's message when nothing of theirs is
        already waiting, and ends with the next message sent to them. Who
        sent it (an agent, or Chat2Work by itself) is recorded on messages
        from version 18.0.1.3.0 of chat2work_ucx on, so the automatic share
        is of the replies where that is known."""
        self.env['comm.interaction'].flush_model()
        self.env['comm.conversation'].flush_model()
        self.env.cr.execute("""
            SELECT cand.id, i.at, i.direction, i.c2w_sender
              FROM comm_interaction i
              JOIN comm_conversation c ON c.id = i.conversation_id
              JOIN comm_channel ch ON ch.id = i.channel_id
              JOIN chat2work_candidate cand ON cand.partner_id = c.partner_id AND cand.active
             WHERE ch.code IN %s AND i.at >= %s AND COALESCE(i.status, '') <> 'failed'
             ORDER BY cand.id, i.at, i.id
        """, [REPLY_CHANNELS, since])
        waits, known, auto, inbound = [], 0, 0, 0
        waiting = {}
        for candidate_id, at, direction, sender in self.env.cr.fetchall():
            if direction == 'inbound':
                inbound += 1
                waiting.setdefault(candidate_id, at)
            elif candidate_id in waiting:
                waits.append((at - waiting.pop(candidate_id)).total_seconds())
                if sender:
                    known += 1
                    auto += sender == 'auto'
        return {
            'inbound': inbound,
            'waits': len(waits),
            'median_seconds': round(median(waits)) if waits else False,
            'quick': round(100 * sum(1 for wait in waits if wait <= QUICK) / len(waits)) if waits else 0,
            'auto_known': known,
            'auto': round(100 * auto / known) if known else 0,
        }

    @api.model
    def _dash_times(self, since):
        """How long people take to finish something on USSD and on WhatsApp.

        A session's time is from its first screen or message to its last
        (chat2work.flow.run, kept from version 18.0.1.23.0 of chat2work on).
        The CV time is from the link being sent to the CV arriving, by how
        the candidate signed up."""
        summary = lambda values: {'n': len(values), 'median': round(median(values)) if values else False}
        runs = self.env['chat2work.flow.run'].sudo().search_read(
            [('started_at', '>=', since)], ['channel', 'outcome', 'seconds'])
        times = {}
        for run in runs:
            times.setdefault((run['outcome'], run['channel']), []).append(run['seconds'])
        rows = [dict({'key': key}, **{channel: summary(times.get((key, channel), [])) for channel in FLOW_CHANNELS})
                for key in PROCESSES]
        sessions = lambda channel: sum(len(v) for (_outcome, ch), v in times.items() if ch == channel)
        left = {channel: {'n': len(times.get(('abandoned', channel), [])), 'of': sessions(channel)}
                for channel in FLOW_CHANNELS}

        cv_times = {channel: [] for channel in FLOW_CHANNELS}
        candidates = self.env['chat2work.candidate'].with_context(active_test=False).search_read(
            [('cv_submitted_at', '>=', since), ('cv_link_sent_at', '!=', False), ('cv_state', 'in', CV_DONE)],
            ['cv_submitted_at', 'cv_link_sent_at', 'registered_via'])
        for row in candidates:
            channel = (row['registered_via'] or '').lower()
            wait = (row['cv_submitted_at'] - row['cv_link_sent_at']).total_seconds()
            # A reminder sent after the CV came in moves the "sent" time past it.
            if channel in cv_times and wait >= 0:
                cv_times[channel].append(wait)
        rows.append(dict({'key': 'cv'}, **{channel: summary(cv_times[channel]) for channel in FLOW_CHANNELS}))
        return {'rows': rows, 'left': left, 'sessions': len(runs)}

    @api.model
    def _dash_cvs(self):
        states = dict(self.env['chat2work.candidate']._read_group([], ['cv_state'], ['__count']))
        done = sum(states.get(state, 0) for state in CV_DONE)
        return {
            'done': done,
            'started': states.get('started', 0),
            'help': states.get('help_requested', 0),
            'none': states.get('none', 0) + states.get(False, 0),
        }

    @api.model
    def _dash_id_checks(self):
        if not self._can_id_check():
            return False
        Candidate = self.env['chat2work.candidate']
        account = self.env['chat2work.verify.account'].sudo().search([], limit=1)
        return {
            'failed': Candidate.search_count(self._list_domain('id_failed')),
            'waiting': Candidate.search_count(self._list_domain('id_waiting')),
            'not_done': Candidate.search_count(self._list_domain('id_not_done')),
            'verified': Candidate.search_count([('id_check_state', '=', 'verified')]),
            'credits': account.available_credits if account and account.balance_at else False,
        }

    @api.model
    def _dash_jobs(self):
        Listing = self.env['chat2work.listing']
        # What needs an agent first, then the ones with the most good matches.
        listings = Listing.search([('work_state', 'in', JOBS_TO_CHECK)], order='closing_on asc nulls last, id desc', limit=4)
        if len(listings) < 4:
            ready = Listing.search([('state', '=', 'open'), ('work_state', 'not in', JOBS_TO_CHECK + ('rejected', 'closed'))],
                                   order='closing_on asc nulls last, id desc', limit=40)
            listings |= ready.sorted(lambda listing: -listing.approved_count)[:4 - len(listings)]
        return {
            'live': Listing.search_count([('state', '=', 'open'), ('work_state', 'not in', ('rejected', 'closed'))]),
            'rows': [{
                'id': listing.id, 'name': listing.title, 'employer': listing.employer or '', 'good': listing.approved_count,
                'to_review': listing.suggested_count, 'work_state': listing.work_state,
                'work_label': self._label(listing, 'work_state'),
            } for listing in listings],
        }

    @api.model
    def _dash_bookings(self):
        Booking = self.env['chat2work.interview.booking']
        now = fields.Datetime.now()
        upcoming = [('state', '=', 'booked'), ('slot_id.start_datetime', '>=', now)]
        bookings = Booking.search(upcoming, limit=200).sorted(lambda b: (b.slot_id.start_datetime, b.id))
        by_partner = self._candidate_by_partner(bookings.partner_id)
        names = {c.id: c.display_name for c in self.env['chat2work.candidate'].browse(list(by_partner.values()))}
        return {
            'week': len(bookings.filtered(lambda b: b.slot_id.start_datetime < now + timedelta(days=7))),
            'rows': [{
                'id': booking.id,
                'at': _dt(booking.slot_id.start_datetime),
                # The candidate's own name where there is one: their contact record may only hold the number.
                'who': names.get(by_partner.get(booking.partner_id.id)) or booking.partner_id.name or booking.phone
                       or _("Unknown caller"),
                'what': booking.job_id.name or '',
                'candidate_id': by_partner.get(booking.partner_id.id, False),
            } for booking in bookings[:4]],
        }

    # ── The call ─────────────────────────────────────────────────────────
    @api.model
    def ws_dashboard(self, period='today'):
        self._check_agent()
        if period not in PERIODS:
            period = 'today'
        tz = self._dash_tz()
        since = self._dash_start(tz, PERIODS[period])
        return {
            'period': period,
            'todo': self._dash_todo(),
            'stages': self.ws_pipeline(),
            'new': self._dash_new_candidates(tz, since),
            'cvs': self._dash_cvs(),
            'times': self._dash_times(since),
            'replies': self._dash_replies(since),
            'ids': self._dash_id_checks(),
            'jobs': self._dash_jobs(),
            'bookings': self._dash_bookings(),
        }
