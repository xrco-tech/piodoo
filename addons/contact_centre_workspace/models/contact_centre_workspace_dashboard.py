# -*- coding: utf-8 -*-
"""The numbers on the Contact Centre dashboard, in one call.

Everything is read as the signed-in user, so they see what their own access
allows (an agent's calls are their own calls). Days and hours are the user's
own: "today" starts at their midnight."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .contact_centre_workspace_ai_ops import CHAT
from .contact_centre_workspace_calls import LINES
from .contact_centre_workspace_campaigns import MANAGER

USER = 'contact_centre.group_contact_centre_user'
PERIODS = {'today': 0, '7d': 6, '30d': 29}
CHART_DAYS = 14
TEXT_CHANNELS = ('whatsapp', 'sms', 'email')
FIRST_HOUR, LAST_HOUR = 6, 19           # busiest hours runs 06:00 to 20:00
QUICK = 15 * 60                         # "answered within 15 minutes"


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

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

    @api.model
    def _dash_local(self, tz, moment):
        return pytz.utc.localize(moment).astimezone(tz)

    # ── The pieces ───────────────────────────────────────────────────────
    @api.model
    def _dash_messages(self, tz, since):
        """Text messages (not calls): one bar per day for the chart, and the period's totals."""
        Message = self.env['contact.centre.message']
        chart_start = self._dash_start(tz, CHART_DAYS - 1)
        first_day = self._dash_local(tz, chart_start).date()
        days = [{'date': fields.Date.to_string(first_day + timedelta(days=i)), 'whatsapp': 0, 'sms': 0, 'email': 0}
                for i in range(CHART_DAYS)]
        rows = Message.search_read(
            [('channel', 'in', TEXT_CHANNELS), ('message_timestamp', '>=', min(chart_start, since))],
            ['channel', 'direction', 'status', 'message_timestamp'])
        totals = {'total': 0, 'inbound': 0, 'outbound': 0, 'failed': 0, 'failed_by': defaultdict(int)}
        for row in rows:
            at = row['message_timestamp']
            index = (self._dash_local(tz, at).date() - first_day).days
            if 0 <= index < CHART_DAYS:
                days[index][row['channel']] += 1
            if at >= since:
                totals['total'] += 1
                totals[row['direction'] if row['direction'] in ('inbound', 'outbound') else 'outbound'] += 1
                if row['status'] == 'failed':
                    totals['failed'] += 1
                    totals['failed_by'][row['channel']] += 1
        totals['failed_by'] = [{'channel': self._channel_label(channel), 'n': n}
                               for channel, n in sorted(totals['failed_by'].items())]
        return dict(totals, days=days)

    @api.model
    def _dash_calls(self, since):
        """Calls of both lines since `since`: how they went, and how long was spent talking."""
        result = {'answered': 0, 'missed': 0, 'outgoing': 0, 'total': 0, 'talk_seconds': 0, 'average_seconds': 0, 'lines': []}
        talked = 0
        for line, (model, direction, _status, at) in LINES.items():
            if model not in self.env:
                continue
            counts = {'line': 'whatsapp' if line == 'wa' else 'voip', 'answered': 0, 'missed': 0, 'outgoing': 0, 'total': 0}
            for call in self.env[model].search([(at, '>=', since)]):
                kind, _words = self._call_outcome(line, call)
                counts['total'] += 1
                if call[direction] != 'incoming':
                    counts['outgoing'] += 1
                elif kind == 'missed':
                    counts['missed'] += 1
                elif kind == 'answered':
                    counts['answered'] += 1
                if kind == 'answered' and call.duration:
                    result['talk_seconds'] += call.duration
                    talked += 1
            result['lines'].append(counts)
            for key in ('answered', 'missed', 'outgoing', 'total'):
                result[key] += counts[key]
        result['average_seconds'] = round(result['talk_seconds'] / talked) if talked else 0
        return result

    @api.model
    def _dash_replies(self, since):
        """How long people waited for a first reply since `since`.

        A wait starts with someone's message when nothing of theirs is
        already waiting, and ends with the next thing that went out to them:
        a reply or a call from the inbox, or a WhatsApp message sent by the
        bot (those are not copied into the thread, so they are read from
        WhatsApp itself and count as answered automatically)."""
        Message = self.env['contact.centre.message']
        events = defaultdict(list)          # contact id -> [(time, kind)]
        for row in Message.search_read(
                [('direction', '=', 'inbound'), ('channel', '!=', 'voice'), ('message_timestamp', '>=', since)],
                ['contact_id', 'message_timestamp']):
            events[row['contact_id'][0]].append((row['message_timestamp'], 'in'))
        if not events:
            return {'waits': 0, 'median_seconds': False, 'quick': 0, 'auto': 0}
        contact_ids = list(events)
        known = set()
        for row in Message.search_read(
                [('contact_id', 'in', contact_ids), ('direction', '=', 'outbound'), ('status', '!=', 'failed'),
                 ('message_timestamp', '>=', since)], ['contact_id', 'message_timestamp', 'provider_message_id']):
            events[row['contact_id'][0]].append((row['message_timestamp'], 'out'))
            if row['provider_message_id']:
                known.add(row['provider_message_id'])
        wa_ids = self._wa_ids(contact_ids)
        by_number = defaultdict(list)
        for contact_id, numbers in wa_ids.items():
            for number in numbers:
                by_number[number].append(contact_id)
        if by_number:
            for row in self.env['whatsapp.message'].sudo().search_read(
                    [('wa_id', 'in', list(by_number)), ('is_incoming', '=', False), ('message_timestamp', '>=', since)],
                    ['wa_id', 'message_timestamp', 'message_id']):
                if row['message_id'] in known:
                    continue        # a reply typed in the inbox: already counted above
                for contact_id in by_number[row['wa_id']]:
                    events[contact_id].append((row['message_timestamp'], 'auto'))
        waits, auto = [], 0
        for moments in events.values():
            waiting = None
            for at, kind in sorted(moments, key=lambda moment: (moment[0], moment[1] != 'in')):
                if kind == 'in':
                    waiting = waiting or at
                elif waiting:
                    waits.append((at - waiting).total_seconds())
                    auto += kind == 'auto'
                    waiting = None
        if not waits:
            return {'waits': 0, 'median_seconds': False, 'quick': 0, 'auto': 0}
        return {
            'waits': len(waits),
            'median_seconds': round(median(waits)),
            'quick': round(100 * sum(1 for wait in waits if wait <= QUICK) / len(waits)),
            'auto': round(100 * auto / len(waits)),
        }

    @api.model
    def _dash_hours(self, tz):
        """Messages and calls that came in over the last 7 days, by the hour of the day."""
        hours = {hour: 0 for hour in range(FIRST_HOUR, LAST_HOUR + 1)}
        for row in self.env['contact.centre.message'].search_read(
                [('direction', '=', 'inbound'), ('message_timestamp', '>=', self._dash_start(tz, 6))], ['message_timestamp']):
            hour = self._dash_local(tz, row['message_timestamp']).hour
            if hour in hours:
                hours[hour] += 1
        return [{'hour': hour, 'n': n} for hour, n in hours.items()]

    @api.model
    def _dash_campaigns(self):
        Campaign = self.env['contact.centre.campaign']
        Message = self.env['contact.centre.message']
        states = dict(Campaign._read_group([], ['state'], ['__count']))
        labels = self._campaign_labels()
        rows = []
        for campaign in (Campaign.search([('state', '=', 'running')], order='date_start desc, id desc', limit=4)
                         | Campaign.search([('state', '=', 'draft')], order='id desc', limit=4))[:4]:
            total = len(campaign.contact_ids)
            rows.append({
                'id': campaign.id,
                'name': campaign.name,
                'state': campaign.state or 'draft',
                'state_label': labels['state'].get(campaign.state or 'draft', ''),
                'outbound': campaign.campaign_type == 'outbound',
                'total': total,
                'done': min(campaign.send_progress, total),
                'failed': Message.search_count([('campaign_id', '=', campaign.id), ('status', '=', 'failed')]),
                'messages': Message.search_count([('campaign_id', '=', campaign.id)]),
            })
        return {'running': states.get('running', 0), 'draft': states.get('draft', 0), 'rows': rows}

    @api.model
    def _dash_held(self):
        """Chats where Sidekick is holding a change for a yes; False when that is not this user's to see."""
        if not self._ai_ops_available():
            return False
        return sum(1 for chat in self.env[CHAT].search([('pending_state', '!=', False)]) if self._ai_held(chat))

    # ── The call ─────────────────────────────────────────────────────────
    @api.model
    def ws_dashboard(self, period='today'):
        if not self.env.user.has_group(USER):
            raise AccessError(_("Only Contact Centre users can see the dashboard."))
        if period not in PERIODS:
            period = 'today'
        tz = self._dash_tz()
        since = self._dash_start(tz, PERIODS[period])
        today = self._dash_start(tz, 0)
        self._flush()

        Contact = self.env['contact.centre.contact']
        open_ids = Contact.search([('state', '!=', 'resolved')], limit=5000).ids
        waiting = self._unread(open_ids, seen=False)
        oldest = min((when for _count, when in waiting.values() if when), default=False)
        states = dict(Contact._read_group([], ['state'], ['__count']))

        Call = self.env['whatsapp.call.log']
        outcomes = Call._read_group(
            [('call_timestamp', '>=', since), ('disposition_id', '!=', False)], ['disposition_id'], ['__count'],
            order='__count desc', limit=6)
        return {
            'period': period,
            'is_manager': self.env.user.has_group(MANAGER),
            'is_agent': self.env.user.has_group('contact_centre.group_contact_centre_agent'),
            'todo': {
                'unread': len(self._unread(open_ids)),
                'waiting_since': fields.Datetime.to_string(oldest) if oldest else False,
                'missed_today': self._dash_calls(today)['missed'],
                'no_outcome': Call.search_count(
                    self._call_domain('wa', 'no_outcome', '') + [('call_timestamp', '>=', self._dash_start(tz, 29))]),
                'held': self._dash_held(),
            },
            'messages': self._dash_messages(tz, since),
            'calls': self._dash_calls(since),
            'conversations': {
                'open': states.get('open', 0) + states.get(False, 0),
                'pending': states.get('pending', 0),
                'resolved': states.get('resolved', 0),
            },
            'replies': self._dash_replies(since),
            'outcomes': [{'name': disposition.name, 'n': n} for disposition, n in outcomes],
            'campaigns': self._dash_campaigns(),
            'hours': self._dash_hours(tz),
        }
