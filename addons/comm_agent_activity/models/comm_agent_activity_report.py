# -*- coding: utf-8 -*-
"""The Team report: what each agent did in a period, read from comm.agent.activity.

The workspaces say who their agents are, what is waiting and where calls are
kept, by extending _sources, _agents, _backlog and _calls."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from statistics import median

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date

from .comm_agent_activity import ACTIONS, SCORED

SUPERVISOR = 'comm_agent_activity.group_supervisor'
PERIODS = ('today', 'week', 'last_week', 'month')
STRETCH_GAP = 15 * 60        # a longer gap between two actions ends a stretch of work
STRETCH_START = 60           # what the first action of a stretch counts for
FAST_CHECK = 60              # a job checked in under a minute, with no note
FAST_MIN, FAST_SHARE = 5, 0.3
FIRST_HOUR, LAST_HOUR = 8, 17
LOG_SHOWN = 30
# The count columns each workspace's report shows.
COLUMNS = {
    'chat2work': ('job_check', 'match', 'employer_check', 'reply'),
    'contact_centre': ('reply', 'close', 'queue_call'),
}
WHY = {
    'employer_check': "Slowest work, and one check covers many jobs",
    'employer_join': "Two spellings of one employer put together",
    'job_check': "Verified, or marked invalid or cancelled",
    'call': "Talk time is shown, not scored",
    'reply': "One for each message answered",
    'close': "A conversation marked resolved",
    'queue_call': "A call from the queue, with what happened",
    'match': "Approved or rejected. Quick to do, so worth least",
    'outreach': "A message nobody was waiting for",
    'reversed': "Another agent had to undo it",
}


def _initials(name):
    words = [word for word in (name or '').split() if word[:1].isalnum()]
    return ''.join(word[0] for word in words[:2]).upper() or '?'


class CommAgentActivityReport(models.AbstractModel):
    _name = 'comm.agent.activity.report'
    _description = 'Team report'

    # ── What the workspaces fill in ──────────────────────────────────────────
    @api.model
    def _sources(self):
        """[(key, label)] of the workspaces installed here that record activity."""
        return []

    @api.model
    def _agents(self, source):
        """The users who are agents of `source` ('both' for every workspace)."""
        return self.env['res.users']

    @api.model
    def _backlog(self, source):
        """Work waiting: [{'key', 'label', 'waiting', 'done', 'new', 'action'}], where
        done and new are counts over the last 7 days and action is the activity that clears it."""
        return []

    @api.model
    def _calls(self, start, end):
        """{user id: [calls, seconds talking]} between two UTC times."""
        return {}

    # ── Who may see what ─────────────────────────────────────────────────────
    @api.model
    def _is_supervisor(self):
        return self.env.user.has_group(SUPERVISOR)

    @api.model
    def _check_source(self, source):
        keys = [key for key, _label in self._sources()]
        if source == 'both' and len(keys) > 1:
            return source
        if source in keys:
            return source
        if not keys:
            raise UserError(self.env._("No workspace that records agent activity is installed."))
        return keys[0]

    # ── Time ─────────────────────────────────────────────────────────────────
    @api.model
    def _tz(self):
        try:
            return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    @api.model
    def _period(self, period):
        """(start, end, start of the period before, label, first day, last day): UTC times as the
        database keeps them, days in the user's time zone."""
        tz = self._tz()
        today = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).date()
        if period == 'week':
            first, last = today - timedelta(days=today.weekday()), today
        elif period == 'last_week':
            first = today - timedelta(days=today.weekday() + 7)
            last = first + timedelta(days=6)
        elif period == 'month':
            first, last = today.replace(day=1), today
        else:
            first = last = today
        utc = lambda day: tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        days = (last - first).days + 1
        if first == last:
            label = format_date(self.env, first, date_format='d MMMM')
        elif first.month == last.month:
            label = self.env._("%(first)s to %(last)s", first=first.day, last=format_date(self.env, last, date_format='d MMMM'))
        else:
            label = self.env._("%(first)s to %(last)s", first=format_date(self.env, first, date_format='d MMMM'),
                      last=format_date(self.env, last, date_format='d MMMM'))
        return utc(first), utc(last + timedelta(days=1)), utc(first - timedelta(days=days)), label, first, last

    @api.model
    def _active_seconds(self, moments):
        """Time worked, from when things were done: gaps of up to 15 minutes count in full."""
        total, previous = 0, None
        for moment in sorted(moments):
            gap = (moment - previous).total_seconds() if previous else None
            total += gap if gap is not None and gap <= STRETCH_GAP else STRETCH_START
            previous = moment
        return round(total)

    # ── The figures ──────────────────────────────────────────────────────────
    @api.model
    def _domain(self, source, start, end):
        domain = [('at', '>=', start), ('at', '<', end)]
        if source != 'both':
            domain.append(('source', '=', source))
        return domain

    @api.model
    def _stats(self, source, start, end):
        """{user id: what they did} from the activity lines between two times."""
        stats = defaultdict(lambda: {'n': defaultdict(int), 'moments': [], 'waits': [], 'reversed': 0,
                                     'check_seconds': [], 'noted': 0, 'fast': 0, 'hours': []})
        rows = self.env['comm.agent.activity'].sudo().search_read(
            self._domain(source, start, end),
            ['user_id', 'at', 'action', 'seconds', 'wait_seconds', 'has_note', 'reversed'], order='at, id')
        for row in rows:
            stat = stats[row['user_id'][0]]
            stat['n'][row['action']] += 1
            stat['moments'].append(row['at'])
            stat['reversed'] += bool(row['reversed'])
            if row['wait_seconds']:
                stat['waits'].append(row['wait_seconds'])
                stat['hours'].append((row['at'] - timedelta(seconds=row['wait_seconds']), row['wait_seconds']))
            if row['action'] == 'job_check':
                stat['noted'] += bool(row['has_note'])
                if row['seconds']:
                    stat['check_seconds'].append(row['seconds'])
                    stat['fast'] += row['seconds'] < FAST_CHECK and not row['has_note']
        return stats

    @api.model
    def _score(self, counts, calls, reversed_n, points):
        total = sum(points.get(action, 0.0) * n for action, n in counts.items())
        return round(total + points.get('call', 0.0) * calls + points.get('reversed', 0.0) * reversed_n)

    @api.model
    def _rows(self, source, start, end):
        """One row per agent of `source` and per anyone else who did something, best score first."""
        stats = self._stats(source, start, end)
        calls = self._calls(start, end)
        points = self.env['comm.agent.activity.points']._all()
        agents = self._agents(source)
        users = agents | self.env['res.users'].sudo().browse(list(set(stats) | set(calls))).exists()
        rows = []
        for user in users.sudo():
            stat = stats.get(user.id)
            n_calls, talk = calls.get(user.id, (0, 0))
            counts = dict(stat['n']) if stat else {}
            checks = counts.get('job_check', 0)
            fast = stat['fast'] if stat else 0
            actions = sum(counts.values()) + n_calls
            rows.append({
                'user_id': user.id,
                'name': user.name,
                'initials': _initials(user.name),
                'actions': actions,
                'counts': counts,
                'active_seconds': self._active_seconds(stat['moments']) if stat else 0,
                'days': len({moment.date() for moment in stat['moments']}) if stat else 0,
                'waits': stat['waits'] if stat else [],
                'wait_median': round(median(stat['waits'])) if stat and stat['waits'] else False,
                'calls': n_calls,
                'talk_seconds': talk,
                'reversed': stat['reversed'] if stat else 0,
                'checks': checks,
                'check_median': round(median(stat['check_seconds'])) if stat and stat['check_seconds'] else False,
                'noted': round(100 * stat['noted'] / checks) if checks else False,
                'fast': fast,
                'fast_flag': fast >= FAST_MIN and fast >= FAST_SHARE * checks,
                'score': self._score(counts, n_calls, stat['reversed'] if stat else 0, points),
                'hours': stat['hours'] if stat else [],
            })
        rows.sort(key=lambda row: (-row['score'], -row['actions'], row['name']))
        return rows

    @api.model
    def _columns(self, source):
        labels = dict(ACTIONS)
        keys = []
        for key in ([source] if source != 'both' else [key for key, _label in self._sources()]):
            keys += [action for action in COLUMNS.get(key, ()) if action not in keys]
        plural = {
            'job_check': self.env._("Jobs checked"), 'match': self.env._("Matches decided"), 'employer_check': self.env._("Employers checked"),
            'reply': self.env._("Replies sent"), 'close': self.env._("Conversations closed"), 'queue_call': self.env._("Queued calls"),
        }
        return [{'key': key, 'label': plural.get(key, labels.get(key, key))} for key in keys]

    @api.model
    def _public(self, row):
        """A row without the lists it was worked out from."""
        return {key: value for key, value in row.items() if key not in ('waits', 'hours')}

    @api.model
    def _hours(self, rows, tz):
        """How long people waited, by the hour of the day they wrote."""
        by_hour = defaultdict(list)
        for row in rows:
            for moment, wait in row['hours']:
                by_hour[pytz.utc.localize(moment).astimezone(tz).hour].append(wait)
        first = min([FIRST_HOUR] + list(by_hour))
        last = max([LAST_HOUR] + list(by_hour))
        return [{'hour': hour, 'n': len(by_hour[hour]), 'median': round(median(by_hour[hour])) if by_hour[hour] else 0}
                for hour in range(first, last + 1)]

    @api.model
    def _planning(self, source):
        """Work waiting against the last 7 days' pace, and the extra hours a week that
        would clear all of it in two weeks."""
        since = fields.Datetime.now() - timedelta(days=30)
        Log = self.env['comm.agent.activity'].sudo()
        rows, extra = [], 0.0
        for item in self._backlog(source):
            taken = Log.search([('action', '=', item['action']), ('at', '>=', since), ('seconds', '>', 0)]).mapped('seconds')
            each = median(taken) if taken else 180
            gain = item['done'] - item['new']
            item['weeks'] = max(1, round(item['waiting'] / gain)) if gain > 0 and item['waiting'] else False
            item['each_seconds'] = round(each)
            extra += max(0.0, item['waiting'] / 2.0 - gain) * each / 3600.0
            rows.append(item)
        return rows, round(extra)

    # ── What the screens read ────────────────────────────────────────────────
    @api.model
    def boot(self, source=None):
        sources = self._sources()
        return {
            'supervisor': self._is_supervisor(),
            'user_id': self.env.uid,
            'sources': [{'key': key, 'label': label} for key, label in sources],
            'source': self._check_source(source or 'both'),
        }

    @api.model
    def team(self, source='both', period='week'):
        """Everyone, for a supervisor."""
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors see every agent. Your own figures are under My activity."))
        source = self._check_source(source)
        period = period if period in PERIODS else 'week'
        start, end, before, label, _first, _last = self._period(period)
        rows = self._rows(source, start, end)
        waits = [wait for row in rows for wait in row['waits']]
        actions = sum(row['actions'] for row in rows)
        earlier = sum(row['actions'] for row in self._rows(source, before, start))
        active = [row for row in rows if row['actions']]
        reversed_n = sum(row['reversed'] for row in rows)
        columns = self._columns(source)
        total = {
            'active_seconds': sum(row['active_seconds'] for row in rows),
            'counts': {col['key']: sum(row['counts'].get(col['key'], 0) for row in rows) for col in columns},
            'wait_median': round(median(waits)) if waits else False,
            'calls': sum(row['calls'] for row in rows),
            'talk_seconds': sum(row['talk_seconds'] for row in rows),
            'reversed': reversed_n,
            'score': sum(row['score'] for row in rows),
        }
        target = int(self.env['ir.config_parameter'].sudo().get_param('comm_agent_activity.reply_target_minutes', 10) or 10)
        backlog, extra = self._planning(source)
        return {
            'source': source,
            'period': period,
            'label': label,
            'columns': columns,
            'rows': [self._public(row) for row in rows],
            'total': total,
            'tiles': {
                'agents': len(rows),
                'active': len(active),
                'actions': actions,
                'change': round(100 * (actions - earlier) / earlier) if earlier else False,
                'active_seconds': total['active_seconds'],
                'wait_median': total['wait_median'],
                'target_seconds': target * 60,
                'reversed': reversed_n,
                'reversed_top': max([row['reversed'] for row in rows] or [0]),
            },
            'backlog': backlog,
            'extra_hours': extra,
            'hours': self._hours(rows, self._tz()),
        }

    @api.model
    def agent(self, user_id=False, source='both', period='week'):
        """One agent beside the team average. Agents may only read their own."""
        user_id = int(user_id or self.env.uid)
        supervisor = self._is_supervisor()
        if user_id != self.env.uid and not supervisor:
            raise AccessError(self.env._("You can only see your own activity."))
        source = self._check_source(source)
        period = period if period in PERIODS else 'week'
        start, end, before, label, first, last = self._period(period)
        tz = self._tz()
        rows = self._rows(source, start, end)
        user = self.env['res.users'].sudo().browse(user_id).exists()
        if not user:
            raise UserError(self.env._("This person no longer exists."))
        blank = {'user_id': user.id, 'name': user.name, 'initials': _initials(user.name), 'actions': 0, 'counts': {},
                 'active_seconds': 0, 'days': 0, 'waits': [], 'wait_median': False, 'calls': 0, 'talk_seconds': 0,
                 'reversed': 0, 'checks': 0, 'check_median': False, 'noted': False, 'fast': 0, 'fast_flag': False,
                 'score': 0, 'hours': []}
        mine = next((row for row in rows if row['user_id'] == user.id), blank)
        active = [row for row in rows if row['actions']]
        mean = lambda values: sum(values) / len(values) if values else False
        whole = lambda value: round(value) if value is not False else False
        team = {
            'score': whole(mean([row['score'] for row in active])),
            'active_seconds': whole(mean([row['active_seconds'] for row in active])),
            'wait_median': whole(mean([row['wait_median'] for row in active if row['wait_median']])),
            'calls': whole(mean([row['calls'] for row in active])),
            'reversed': whole(mean([row['reversed'] for row in active])),
            'checks': whole(mean([row['checks'] for row in active])),
            'check_median': whole(mean([row['check_median'] for row in active if row['check_median']])),
            'noted': whole(mean([row['noted'] for row in active if row['noted'] is not False])),
            'counts': {},
        }
        columns = self._columns(source)
        for col in columns:
            team['counts'][col['key']] = whole(mean([row['counts'].get(col['key'], 0) for row in active]))
        earlier = next((row['score'] for row in self._rows(source, before, start) if row['user_id'] == user.id), 0)

        Log = self.env['comm.agent.activity'].sudo()
        domain = self._domain(source, start, end) + [('user_id', '=', user.id)]
        local = lambda moment: pytz.utc.localize(moment).astimezone(tz)
        by_day = defaultdict(list)
        for row in Log.search_read(domain, ['at']):
            by_day[local(row['at']).date()].append(row['at'])
        days = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            days.append({'label': format_date(self.env, day, date_format='EEE d' if (last - first).days > 6 else 'EEE'),
                         'seconds': self._active_seconds(by_day.get(day, []))})
        labels = dict(Log._fields['action']._description_selection(self.env))
        today_start = self._period('today')[0]
        today = defaultdict(int)
        for row in Log.search_read([('user_id', '=', user.id), ('at', '>=', today_start)]
                                   + ([('source', '=', source)] if source != 'both' else []), ['action']):
            today[row['action']] += 1
        log = [{
            'id': row.id,
            'at': fields.Datetime.to_string(row.at),
            'action': labels.get(row.action, row.action),
            'name': row.name or '',
            'result': row.result_label or '',
            'seconds': row.seconds,
            'wait_seconds': row.wait_seconds,
            'no_note': row.action in ('job_check', 'employer_check') and not row.has_note,
            'fast': row.action == 'job_check' and bool(row.seconds) and row.seconds < FAST_CHECK and not row.has_note,
            'reversed_by': row.reversed_by_id.name if row.reversed else '',
        } for row in Log.search(domain, limit=LOG_SHOWN)]
        return {
            'supervisor': supervisor,
            'own': user.id == self.env.uid,
            'source': source,
            'period': period,
            'label': label,
            'columns': columns,
            'me': self._public(mine),
            'team': team,
            'agents': len(active),
            'score_before': earlier,
            'days': days,
            'today': [{'label': labels[key], 'n': today[key]} for key, _label in ACTIONS if today.get(key)],
            'log': log,
        }

    @api.model
    def points(self):
        """The points per action, most first, with a line on why."""
        values = self.env['comm.agent.activity.points']._all()
        labels = dict(SCORED)
        rows = [{'action': key, 'label': labels[key], 'why': WHY.get(key, ''), 'points': values[key]} for key in labels]
        rows.sort(key=lambda row: -row['points'])
        return {'can_edit': self._is_supervisor(), 'rows': rows}

    @api.model
    def points_save(self, values):
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors set the points."))
        Points = self.env['comm.agent.activity.points'].sudo()
        known = dict(SCORED)
        for action, value in (values or {}).items():
            if action not in known:
                continue
            try:
                number = float(str(value).replace(',', '.'))
            except ValueError:
                raise UserError(self.env._("Points for \"%s\" must be a number.", known[action]))
            row = Points.search([('action', '=', action)], limit=1)
            if row:
                row.points = number
            else:
                Points.create({'action': action, 'points': number})
        return self.points()
