# -*- coding: utf-8 -*-
"""Targets: what each agent should reach, and how far along they are.

A target is a number for one thing that is measured, for everyone or for one
agent. Daily targets are judged on today's figures, weekly ones on the week
so far. Nothing is on until a supervisor switches it on."""
from datetime import datetime, time, timedelta
from statistics import median

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date

from .comm_agent_activity_report import _initials

WORK_DAYS = 5            # Monday to Friday
HISTORY_DAYS = 5
# kind: 'min' is "at least", 'max' is "no more than". Counts are per working day unless period is week.
METRICS = [
    {'key': 'job_check', 'label': 'Jobs checked', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('chat2work',), 'default': 20},
    {'key': 'employer_check', 'label': 'Employers checked', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('chat2work',), 'default': 8},
    {'key': 'match', 'label': 'Matches decided', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('chat2work',), 'default': 40},
    {'key': 'reply', 'label': 'Replies sent', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('chat2work', 'contact_centre'), 'default': 30},
    {'key': 'close', 'label': 'Conversations closed', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('contact_centre',), 'default': 15},
    {'key': 'queue_call', 'label': 'Queued calls wrapped up', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('contact_centre',), 'default': 20},
    {'key': 'call', 'label': 'Calls made or answered', 'kind': 'min', 'period': 'day', 'unit': 'count',
     'sources': ('chat2work', 'contact_centre'), 'default': 20},
    {'key': 'wait', 'label': 'Reply wait', 'kind': 'max', 'period': 'day', 'unit': 'minutes',
     'sources': ('chat2work', 'contact_centre'), 'default': 10},
    {'key': 'noted', 'label': 'Job checks with a note', 'kind': 'min', 'period': 'day', 'unit': 'percent',
     'sources': ('chat2work',), 'default': 80},
    {'key': 'reversed', 'label': 'Decisions reversed later', 'kind': 'max', 'period': 'week', 'unit': 'count',
     'sources': ('chat2work', 'contact_centre'), 'default': 2},
    {'key': 'score', 'label': 'Score', 'kind': 'min', 'period': 'week', 'unit': 'points',
     'sources': ('chat2work', 'contact_centre'), 'default': 750},
]
BY_KEY = {metric['key']: metric for metric in METRICS}
COUNTED = ('job_check', 'employer_check', 'match', 'reply', 'close', 'queue_call')


def _number(value, label):
    try:
        number = float(str(value).replace(',', '.').strip())
    except ValueError:
        number = -1
    if number < 0:
        raise UserError("The target for \"%s\" must be a number, 0 or more." % label)
    return number


class CommAgentActivityTarget(models.Model):
    _name = 'comm.agent.activity.target'
    _description = 'Target for agents'
    _order = 'user_id, id'
    _rec_name = 'metric'

    metric = fields.Selection([(metric['key'], metric['label']) for metric in METRICS], required=True)
    user_id = fields.Many2one('res.users', 'Only for', ondelete='cascade', index=True,
                              help="Empty: the target is for every agent.")
    value = fields.Float(required=True)
    on = fields.Boolean(default=True, help="For a target that is for everyone: whether it is used.")
    note = fields.Char('Why', help="Why this agent's targets are different.")

    @api.model
    def _for_everyone(self):
        """{metric: (value, on)}: what is saved, else the suggested number, switched off."""
        saved = {row.metric: (row.value, row.on) for row in self.sudo().search([('user_id', '=', False)])}
        return {metric['key']: saved.get(metric['key'], (float(metric['default']), False)) for metric in METRICS}

    @api.model
    def _for_users(self, users):
        """{user id: {metric: value}}: everyone's targets that are on, with each agent's own on top."""
        base = {key: value for key, (value, on) in self._for_everyone().items() if on}
        result = {user.id: dict(base) for user in users}
        for row in self.sudo().search([('user_id', 'in', users.ids)]):
            result[row.user_id.id][row.metric] = row.value
        return result


class CommAgentActivityReport(models.AbstractModel):
    _inherit = 'comm.agent.activity.report'

    # ── Working it out ───────────────────────────────────────────────────────
    @api.model
    def _metrics(self, source='both'):
        """The measured things that make sense for `source`, among the workspaces installed."""
        installed = {key for key, _label in self._sources()}
        wanted = installed if source == 'both' else {source} & installed
        return [metric for metric in METRICS if wanted & set(metric['sources'])]

    @api.model
    def _all_source(self):
        return self._check_source('both')

    @api.model
    def _utc(self, day):
        return self._tz().localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _today(self):
        return pytz.utc.localize(fields.Datetime.now()).astimezone(self._tz()).date()

    @api.model
    def _day_rows(self, first, last):
        """{user id: row} for whole days, first to last, over every workspace."""
        rows = self._rows(self._all_source(), self._utc(first), self._utc(last + timedelta(days=1)))
        return {row['user_id']: row for row in rows}

    @api.model
    def _measured(self, key, row):
        """What `row` says for a metric, or None when there is nothing to judge yet."""
        if not row:
            return None if key in ('wait', 'noted') else 0
        if key in COUNTED:
            return row['counts'].get(key, 0)
        if key == 'call':
            return row['calls']
        if key == 'wait':
            return round(row['wait_median'] / 60.0, 1) if row['wait_median'] else None
        if key == 'noted':
            return row['noted'] if row['noted'] is not False else None
        return row[key]          # reversed, score

    @api.model
    def _judge(self, key, target, row):
        metric = BY_KEY[key]
        value = self._measured(key, row)
        if value is None:
            reached = metric['kind'] == 'max'        # a limit holds until it is broken
        elif metric['kind'] == 'min':
            reached = value >= target
        else:
            reached = value <= target
        share = 100 if not target and (reached or value) else (100.0 * (value or 0) / target if target else 0)
        item = {
            'metric': key, 'label': self.env._(metric['label']), 'kind': metric['kind'], 'unit': metric['unit'],
            'period': metric['period'], 'value': value, 'target': target, 'reached': reached,
            'pct': max(0, min(100, round(share))),
        }
        if key == 'noted' and row and row['checks']:
            item['missing'] = row['checks'] - round(row['checks'] * (row['noted'] or 0) / 100.0)
            item['checks'] = row['checks']
        return item

    @api.model
    def _judge_all(self, targets, today_row, week_row, source='both'):
        """(today's items, this week's items) for one agent's targets."""
        today, week = [], []
        for metric in self._metrics(source):
            key = metric['key']
            if key not in targets:
                continue
            if metric['period'] == 'day':
                today.append(self._judge(key, targets[key], today_row))
            else:
                week.append(self._judge(key, targets[key], week_row))
        return today, week

    # ── What an agent sees ───────────────────────────────────────────────────
    @api.model
    def progress(self, source='both', user_id=False, history=False):
        """An agent's progress on their targets: today, this week and, when asked, the last working days."""
        user_id = int(user_id or self.env.uid)
        if user_id != self.env.uid and not self._is_supervisor():
            raise AccessError(self.env._("You can only see your own progress."))
        user = self.env['res.users'].sudo().browse(user_id).exists()
        targets = self.env['comm.agent.activity.target']._for_users(user).get(user.id, {}) if user else {}
        relevant = {metric['key'] for metric in self._metrics(source)}
        targets = {key: value for key, value in targets.items() if key in relevant}
        if not targets:
            return {'today': [], 'week': [], 'reached': 0, 'of': 0, 'history': []}
        day = self._today()
        monday = day - timedelta(days=day.weekday())
        today, week = self._judge_all(targets, self._day_rows(day, day).get(user.id),
                                      self._day_rows(monday, day).get(user.id), source)
        # Pace is judged on the working days already finished, so nobody is behind on a Monday morning.
        done = min(WORK_DAYS, day.weekday())
        for item in week:
            if item['metric'] == 'score':
                item['days_done'] = done
                item['on_pace'] = item['value'] >= item['target'] * done / float(WORK_DAYS)
        past = []
        if history and today:
            days, cursor = [], day
            while len(days) < HISTORY_DAYS:
                if cursor.weekday() < WORK_DAYS:
                    days.append(cursor)
                cursor -= timedelta(days=1)
            for one in reversed(days):
                items = today if one == day else self._judge_all(
                    targets, self._day_rows(one, one).get(user.id), None, source)[0]
                past.append({
                    'label': self.env._("Today") if one == day else format_date(self.env, one, date_format='EEE'),
                    'reached': sum(item['reached'] for item in items), 'of': len(items)})
        return {
            'today': today, 'week': week,
            'reached': sum(item['reached'] for item in today), 'of': len(today),
            'history': past,
        }

    # ── What a supervisor sees ───────────────────────────────────────────────
    @api.model
    def _team_targets(self, source):
        """Today's progress of every agent of `source` on their own daily targets."""
        agents = self._agents(source).sudo()
        if not agents:
            return {'columns': [], 'rows': []}
        Target = self.env['comm.agent.activity.target']
        targets = Target._for_users(agents)
        own = set(Target.sudo().search([('user_id', 'in', agents.ids)]).mapped('user_id').ids)
        day = self._today()
        by_user = self._day_rows(day, day)
        columns = [metric for metric in self._metrics(source) if metric['period'] == 'day'
                   and any(metric['key'] in targets[user.id] for user in agents)]
        rows = []
        for user in agents:
            mine = {key: value for key, value in targets[user.id].items()}
            cells = [self._judge(metric['key'], mine[metric['key']], by_user.get(user.id))
                     if metric['key'] in mine else False for metric in columns]
            judged = [cell for cell in cells if cell]
            if judged:
                rows.append({
                    'user_id': user.id, 'name': user.name,
                    'initials': _initials(user.name),
                    'own': user.id in own, 'cells': cells,
                    'reached': sum(cell['reached'] for cell in judged), 'of': len(judged)})
        rows.sort(key=lambda row: (-row['reached'] / float(row['of']), row['name']))
        return {'columns': [{'key': metric['key'], 'label': self.env._(metric['label'])} for metric in columns],
                'rows': rows}

    @api.model
    def team(self, source='both', period='week', agents=None):
        result = super().team(source, period, agents)
        result['targets'] = self._team_targets(result['source'])
        if result['picked']:
            result['targets']['rows'] = [row for row in result['targets']['rows'] if row['user_id'] in result['picked']]
        wait = self.env['comm.agent.activity.target']._for_everyone()['wait']
        if wait[1] and wait[0]:
            result['tiles']['target_seconds'] = round(wait[0] * 60)
        return result

    @api.model
    def agent(self, user_id=False, source='both', period='week'):
        result = super().agent(user_id, source, period)
        result['progress'] = self.progress(result['source'], result['me']['user_id'], history=True)
        return result

    @api.model
    def _now(self, source):
        """What the team does now, per measured thing, over the last 7 days."""
        end = fields.Datetime.now()
        rows = [row for row in self._rows(self._all_source(), end - timedelta(days=7), end) if row['actions']]
        days = sum(row['days'] for row in rows) or 1
        mean = lambda values: sum(values) / float(len(values)) if values else False
        waits = [wait for row in rows for wait in row['waits']]
        now = {key: round(sum(row['counts'].get(key, 0) for row in rows) / float(days)) for key in COUNTED}
        now.update({
            'call': round(sum(row['calls'] for row in rows) / float(days)),
            'wait': round(median(waits) / 60.0, 1) if waits else False,
            'noted': round(mean([row['noted'] for row in rows if row['noted'] is not False]) or 0)
            if any(row['noted'] is not False for row in rows) else False,
            'reversed': round(mean([row['reversed'] for row in rows]) or 0) if rows else False,
            'score': round(mean([row['score'] for row in rows]) or 0) if rows else False,
        })
        return now, len(rows)

    @api.model
    def _effects(self, source, everyone, agents):
        """What the daily targets add up to against the work waiting."""
        targets = self.env['comm.agent.activity.target']._for_users(agents)
        lines = []
        for item in self._backlog(source):
            key = item['action']
            total = sum(targets[user.id].get(key, 0) for user in agents)
            if not total:
                continue
            new = item['new'] / float(WORK_DAYS)
            gain = total - new
            if not item['waiting']:
                text = self.env._("%(total)s a day. Nothing is waiting now.", total=round(total))
            elif gain <= 0:
                text = self.env._("%(total)s a day does not keep up with about %(new)s new a day.",
                                  total=round(total), new=round(new))
            else:
                days = max(1, round(item['waiting'] / gain))
                text = self.env._(
                    "%(total)s a day against about %(new)s new a day. The %(waiting)s waiting are cleared in about %(days)s.",
                    total=round(total), new=round(new), waiting=item['waiting'],
                    days=self.env._("1 working day") if days == 1 else self.env._("%s working days", days))
            lines.append({'key': item['key'], 'title': item['label'][:1].upper() + item['label'][1:], 'text': text})
        return lines

    @api.model
    def targets(self, source='both'):
        """The targets screen: everyone's targets, the agents with their own, and what they add up to."""
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors set targets."))
        source = self._check_source(source)
        Target = self.env['comm.agent.activity.target']
        everyone = Target._for_everyone()
        now, active = self._now(source)
        agents = self._agents('both').sudo()
        people = {}
        for row in Target.sudo().search([('user_id', '!=', False)]):
            person = people.setdefault(row.user_id.id, {
                'user_id': row.user_id.id, 'name': row.user_id.name,
                'initials': _initials(row.user_id.name),
                'note': '', 'values': {}})
            person['values'][row.metric] = row.value
            person['note'] = person['note'] or row.note or ''
        return {
            'source': source,
            'rows': [{
                'metric': metric['key'], 'label': self.env._(metric['label']), 'kind': metric['kind'],
                'unit': metric['unit'], 'period': metric['period'],
                'value': everyone[metric['key']][0], 'on': everyone[metric['key']][1], 'now': now[metric['key']],
            } for metric in self._metrics('both')],
            'people': sorted(people.values(), key=lambda person: person['name']),
            'agents': [{'id': user.id, 'name': user.name} for user in agents.sorted('name')],
            'agent_count': len(agents),
            'active': active,
            'effects': self._effects('both', everyone, agents),
        }

    @api.model
    def targets_save(self, values):
        """values: {metric: {'on': bool, 'value': number}} for every agent."""
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors set targets."))
        Target = self.env['comm.agent.activity.target'].sudo()
        for key, vals in (values or {}).items():
            if key not in BY_KEY:
                continue
            on = bool(vals.get('on'))
            raw = vals.get('value')
            if raw in (None, False, '') and not on:
                continue
            number = _number(raw, BY_KEY[key]['label'])
            row = Target.search([('metric', '=', key), ('user_id', '=', False)], limit=1)
            if row:
                row.write({'value': number, 'on': on})
            else:
                Target.create({'metric': key, 'value': number, 'on': on})
        return self.targets()

    @api.model
    def target_person_save(self, user_id, note='', values=None):
        """One agent's own targets: {metric: number, or '' for the same as everyone}."""
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors set targets."))
        user = self.env['res.users'].sudo().browse(int(user_id or 0)).exists()
        if not user:
            raise UserError(self.env._("Choose an agent."))
        Target = self.env['comm.agent.activity.target'].sudo()
        Target.search([('user_id', '=', user.id)]).unlink()
        rows = [{'metric': key, 'user_id': user.id, 'value': _number(raw, BY_KEY[key]['label']),
                 'note': (note or '').strip() or False}
                for key, raw in (values or {}).items() if key in BY_KEY and str(raw if raw is not None else '').strip()]
        if not rows:
            raise UserError(self.env._("Give at least one target that is different for this agent, or remove them."))
        Target.create(rows)
        return self.targets()

    @api.model
    def target_person_remove(self, user_id):
        if not self._is_supervisor():
            raise AccessError(self.env._("Only supervisors set targets."))
        self.env['comm.agent.activity.target'].sudo().search([('user_id', '=', int(user_id or 0))]).unlink()
        return self.targets()
