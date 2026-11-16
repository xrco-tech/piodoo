# -*- coding: utf-8 -*-
"""Figures behind the Comm Billing reports screen and the monthly statement.

Everything is read straight from the event ledger. Amounts are the ledger's
`price_local` in the company currency; events that could not be converted
(stored in another currency) are counted separately and left out of the sums.
"""
import calendar
from datetime import date, datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date

CHANNEL_ORDER = ['whatsapp', 'voice', 'other', 'sms', 'ussd']

GROUPS = {
    # key: (SQL expressions to group on)
    'category': ['e.channel', 'e.category'],
    'campaign': ['e.campaign_id'],
    'account': ['e.channel', 'e.account_ref'],
    'country': ['e.country_id'],
    'contact': ['e.partner_id'],
    'source': ['e.source', 'e.feature'],
}
SOURCES = ('chat2work', 'contact_centre', 'other')
ROW_LIMIT = 200


class CommBillingReport(models.AbstractModel):
    _name = 'comm.billing.report'
    _description = 'Communication billing reports'

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------
    @api.model
    def _channel_label(self, channel):
        return {
            'whatsapp': _('WhatsApp'),
            'voice': _('Voice'),
            'other': _('AI'),
            'sms': _('SMS'),
            'ussd': _('USSD'),
        }.get(channel, channel or _('Other'))

    @api.model
    def _channel_hint(self, channel):
        return {
            'whatsapp': _('messages and calls'),
            'voice': _('phone calls'),
            'other': _('chatbot, copilot and Sidekick'),
            'sms': _('text messages'),
            'ussd': _('menu sessions'),
        }.get(channel, '')

    @api.model
    def _category_label(self, category):
        return {
            'marketing': _('Marketing messages'),
            'utility': _('Utility messages'),
            'authentication': _('Sign-in codes'),
            'auth_international': _('Sign-in codes, international'),
            'service': _('Replies and free-form messages'),
            'mba_token': _('Marketing messages (token)'),
            'call_minute': _('Call minutes'),
            'sms_outbound_domestic': _('Messages sent, local'),
            'sms_outbound_intl': _('Messages sent, international'),
            'sms_inbound': _('Messages received'),
            'sms_two_way': _('Two-way messages'),
            'sms_premium': _('Short-code messages'),
            'ussd_session': _('Sessions'),
            'ussd_push': _('Push menus'),
            'voice_inbound': _('Incoming calls'),
            'voice_outbound_local_mobile': _('Calls to cellphones'),
            'voice_outbound_local_fixed': _('Calls to landlines'),
            'voice_outbound_intl': _('International calls'),
            'llm_input': _('Reading (input)'),
            'llm_output': _('Writing (output)'),
            'llm_cache_read': _('Reading again from memory (cache)'),
            'llm_cache_write': _('Saving to memory (cache)'),
        }.get(category, category or _('Other'))

    @api.model
    def _feature_label(self, feature):
        return {
            'sidekick': _('Sidekick (AI)'),
            'ai_ops': _('Sidekick (AI)'),
            'copilot': _('Copilot (AI)'),
            'cv_rebuild': _('Reading CVs (AI)'),
            'occupation': _('Matching occupations (AI)'),
            'chatbot': _('Chatbot (AI)'),
            'job_alert': _('Job alerts'),
            'ussd': _('USSD menu'),
        }.get(feature, feature)

    @api.model
    def _unit_label(self, unit):
        return {
            'message': _('messages'),
            'segment': _('parts'),
            'session': _('sessions'),
            'block': _('charged blocks'),
            'minute': _('min'),
            'kilotoken': _('thousand tokens'),
            'conversation': _('conversations'),
        }.get(unit, '')

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------
    def _tz(self):
        try:
            return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _today(self):
        return datetime.now(self._tz()).date()

    def _utc(self, day):
        """Start of local `day` as a naive UTC datetime."""
        local = self._tz().localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _bounds(self, date_from, date_to):
        """UTC [start, end) covering the local days date_from..date_to."""
        return self._utc(date_from), self._utc(date_to + timedelta(days=1))

    def _period(self, period, date_from=None, date_to=None):
        """Resolve a period key to (from, to, previous from, previous to)."""
        today = self._today()
        first = today.replace(day=1)
        if period == 'last_month':
            start, end = first - relativedelta(months=1), first - timedelta(days=1)
            p_start, p_end = start - relativedelta(months=1), start - timedelta(days=1)
        elif period == '3m':
            start, end = first - relativedelta(months=2), today
            p_start, p_end = start - relativedelta(months=3), start - timedelta(days=1)
        elif period == 'custom':
            try:
                start = fields.Date.to_date(date_from)
                end = fields.Date.to_date(date_to)
            except ValueError:
                start = end = None
            if not start or not end or end < start:
                raise UserError(_('Pick a start date and an end date that is not before it.'))
            length = (end - start).days + 1
            p_start, p_end = start - timedelta(days=length), start - timedelta(days=1)
        else:
            period = 'month'
            start, end = first, today
            # The same days of last month, so the two are comparable.
            p_start = first - relativedelta(months=1)
            p_end = min(p_start + timedelta(days=(end - start).days),
                        first - timedelta(days=1))
        return period, start, end, p_start, p_end

    def _span_label(self, start, end):
        if start == end:
            return format_date(self.env, start, date_format='d MMMM y')
        if (start.year, start.month) == (end.year, end.month):
            return _('%(from)s to %(to)s', **{
                'from': str(start.day),
                'to': format_date(self.env, end, date_format='d MMMM y')})
        return _('%(from)s to %(to)s', **{
            'from': format_date(self.env, start, date_format='d MMMM'),
            'to': format_date(self.env, end, date_format='d MMMM y')})

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def _cost_sql(self):
        """Ledger cost in the company currency (unconverted events excluded)."""
        return ('COALESCE(SUM(e.price_local) FILTER '
                '(WHERE e.currency_id = %(cur)s), 0)')

    def _source(self):
        source = self.env.context.get('billing_source')
        return source if source in SOURCES else None

    def _source_sql(self):
        """Limits a query to one source when the screen asked for one. Charges
        recorded before sources existed are NULL and count as 'other'."""
        return "AND COALESCE(e.source, 'other') = %(src)s" if self._source() else ''

    def _source_domain(self):
        source = self._source()
        if not source:
            return []
        return [('source', 'in', [False, 'other'])] if source == 'other' else [('source', '=', source)]

    @api.model
    def _source_label(self, source):
        return {
            'chat2work': _('Chat2Work'),
            'contact_centre': _('Contact Centre'),
        }.get(source, _('Not attributed'))

    def _params(self, start, end, **extra):
        # Every query here is raw SQL: make sure pending ORM writes are in the table.
        self.env['comm.billing.event'].flush_model()
        utc_start, utc_end = self._bounds(start, end)
        return dict(start=utc_start, end=utc_end, src=self._source(),
                    cur=self.env.company.currency_id.id, **extra)

    def _by_channel(self, start, end):
        """{channel: {cost, free_qty, unpriced, unconverted}} for local days."""
        self.env.cr.execute(f"""
            SELECT e.channel,
                   {self._cost_sql()},
                   COALESCE(SUM(e.unit_qty) FILTER (WHERE e.is_free), 0),
                   COUNT(*) FILTER (WHERE e.rate_id IS NULL AND NOT COALESCE(e.is_free, FALSE)),
                   COUNT(*) FILTER (WHERE e.price_usd > 0 AND e.currency_id IS DISTINCT FROM %(cur)s)
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s {self._source_sql()}
             GROUP BY e.channel
        """, self._params(start, end))
        return {
            channel: {'cost': cost, 'free_qty': free, 'unpriced': unpriced,
                      'unconverted': unconverted}
            for channel, cost, free, unpriced, unconverted in self.env.cr.fetchall()
        }

    def _by_day(self, start, end):
        """{local date: cost}."""
        self.env.cr.execute(f"""
            SELECT (e.event_date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS day,
                   {self._cost_sql()}
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s {self._source_sql()}
             GROUP BY day
        """, self._params(start, end, tz=self._tz().zone))
        return dict(self.env.cr.fetchall())

    def _rows(self, start, end, group_by):
        exprs = GROUPS[group_by]
        keys = ', '.join(exprs)
        self.env.cr.execute(f"""
            SELECT {keys},
                   SUM(e.unit_qty),
                   COALESCE(SUM(e.unit_qty) FILTER (WHERE e.is_free), 0),
                   {self._cost_sql()},
                   MIN(e.unit), COUNT(DISTINCT e.unit), COUNT(*)
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s {self._source_sql()}
             GROUP BY {keys}
             ORDER BY {len(exprs) + 3} DESC, {len(exprs) + 1} DESC
             LIMIT {ROW_LIMIT}
        """, self._params(start, end))
        return self.env.cr.fetchall()

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------
    def _budget_state(self, budget, month=None):
        """Where the month stands against `budget`. `month` defaults to this one."""
        if not budget or not (budget.amount or budget.limits()):
            return None
        today = self._today()
        first = (month or today).replace(day=1)
        days_in_month = calendar.monthrange(first.year, first.month)[1]
        last = first.replace(day=days_in_month)
        current = (first.year, first.month) == (today.year, today.month)
        end = today if current else last
        channels = {ch: v['cost'] for ch, v in self._by_channel(first, end).items()}
        spent = sum(channels.values())
        forecast = None
        elapsed = days_in_month
        if current:
            now = datetime.now(self._tz()).replace(tzinfo=None)
            elapsed = max((now - datetime.combine(first, time.min)).total_seconds() / 86400.0, 0.5)
            forecast = spent / elapsed * days_in_month
        return {
            'month': first,
            'month_label': format_date(self.env, first, date_format='MMMM y'),
            'current': current,
            'amount': budget.amount,
            'spent': spent,
            'left': budget.amount - spent,
            'pct': round(spent / budget.amount * 100) if budget.amount else 0,
            'today_pct': round(elapsed / days_in_month * 100) if current else 100,
            'days_elapsed': elapsed,
            'days_left': days_in_month - today.day + 1 if current else 0,
            'forecast': forecast,
            'channels': channels,
            'limits': budget.limits(),
            'days': {str(d): c for d, c in self._by_day(first, end).items()},
        }

    # ------------------------------------------------------------------
    # Reports screen
    # ------------------------------------------------------------------
    @api.model
    def overview(self, period='month', date_from=None, date_to=None,
                 group_by='category', source=None):
        self.env['comm.billing.event'].check_access('read')
        self = self.with_context(billing_source=source if source in SOURCES else None)
        source = self._source()
        if group_by not in GROUPS:
            group_by = 'category'
        period, start, end, p_start, p_end = self._period(period, date_from, date_to)
        today = self._today()
        currency = self.env.company.currency_id

        now = self._by_channel(start, end)
        before = self._by_channel(p_start, p_end)
        spent = sum(v['cost'] for v in now.values())
        prev = sum(v['cost'] for v in before.values())

        budget = self.env['comm.billing.budget']._for_company()
        state = None
        # The budget is for everything together, so it only shows unfiltered.
        if period in ('month', 'last_month') and not source:
            state = self._budget_state(budget, month=start)
        limits = state['limits'] if state else {}

        top = max((v['cost'] for v in now.values()), default=0.0)
        channels = []
        for channel in sorted(set(now) | set(limits),
                              key=lambda c: (-now.get(c, {}).get('cost', 0.0),
                                             CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else 99)):
            cost = now.get(channel, {}).get('cost', 0.0)
            limit = limits.get(channel)
            channels.append({
                'key': channel,
                'label': self._channel_label(channel),
                'hint': self._channel_hint(channel),
                'cost': cost,
                'share': round(cost / spent * 100) if spent else 0,
                'bar': round(cost / top * 100) if top else 0,
                'change': cost - before.get(channel, {}).get('cost', 0.0),
                'limit': limit,
                'limit_pct': round(cost / limit * 100) if limit else None,
            })

        forecast = None
        if period == 'month':
            if state:
                forecast = state['forecast']
            else:
                days_in_month = calendar.monthrange(start.year, start.month)[1]
                local_now = datetime.now(self._tz()).replace(tzinfo=None)
                elapsed = max((local_now - datetime.combine(start, time.min)).total_seconds() / 86400.0, 0.5)
                forecast = spent / elapsed * days_in_month

        budget_block = None
        if state and state['amount']:
            over = (state['forecast'] if state['current'] else state['spent']) - state['amount']
            budget_block = {
                'month_label': state['month_label'],
                'current': state['current'],
                'amount': state['amount'],
                'spent': state['spent'],
                'left': state['left'],
                'pct': state['pct'],
                'bar': min(state['pct'], 100),
                'today_pct': state['today_pct'],
                'days_left': state['days_left'],
                'per_day': (state['left'] / state['days_left']
                            if state['current'] and state['days_left'] and state['left'] > 0 else 0),
                'over': over,
            }

        return {
            'currency_id': currency.id,
            'period': period,
            'date_from': str(start),
            'date_to': str(end),
            'span': self._span_label(start, end),
            'prev_span': self._span_label(p_start, p_end),
            'spent': spent,
            'prev': prev,
            'change_pct': round((spent - prev) / prev * 100) if prev else None,
            'forecast': forecast,
            'free_qty': sum(v['free_qty'] for v in now.values()),
            'unpriced': sum(v['unpriced'] for v in now.values()),
            'unconverted': sum(v['unconverted'] for v in now.values()),
            'budget': budget_block,
            'has_budget': bool(budget and (budget.amount or budget.limits())),
            'can_configure': self.env['comm.billing.budget'].has_access('write'),
            'channels': channels,
            'days': self._days(start, end, today),
            'domain': [('event_date', '>=', fields.Datetime.to_string(self._utc(start))),
                       ('event_date', '<', fields.Datetime.to_string(
                           self._utc(end + timedelta(days=1))))] + self._source_domain(),
            'source': source or '',
            'sources': [{'key': key, 'label': self._source_label(key)} for key in SOURCES],
            'group_by': group_by,
            'rows': self._table_rows(start, end, group_by, spent),
        }

    def _days(self, start, end, today):
        """Bars for the spend chart: one a day, or one a week on long spans."""
        by_day = self._by_day(start, end)
        length = (end - start).days + 1
        bars = []
        if length <= 45:
            for offset in range(length):
                day = start + timedelta(days=offset)
                bars.append({
                    'key': str(day),
                    'short': str(day.day),
                    'label': format_date(self.env, day, date_format='d MMMM'),
                    'cost': by_day.get(day, 0.0),
                    'from': str(day), 'to': str(day),
                })
        else:
            cursor = start
            while cursor <= end:
                week_end = min(cursor + timedelta(days=6), end)
                cost = sum(c for d, c in by_day.items() if cursor <= d <= week_end)
                bars.append({
                    'key': str(cursor),
                    'short': format_date(self.env, cursor, date_format='d MMM'),
                    'label': self.env._('Week of %s', format_date(
                        self.env, cursor, date_format='d MMMM')),
                    'cost': cost,
                    'from': str(cursor), 'to': str(week_end),
                })
                cursor = week_end + timedelta(days=1)
        top = max((b['cost'] for b in bars), default=0.0)
        for bar in bars:
            bar['domain'] = [
                ('event_date', '>=', fields.Datetime.to_string(
                    self._utc(fields.Date.to_date(bar.pop('from'))))),
                ('event_date', '<', fields.Datetime.to_string(
                    self._utc(fields.Date.to_date(bar.pop('to')) + timedelta(days=1))))
            ] + self._source_domain()
            bar['height'] = round(bar['cost'] / top * 100) if top else 0
            bar['peak'] = bool(top) and bar['cost'] == top
        return {
            'bars': bars,
            'weekly': length > 45,
            'average': sum(b['cost'] for b in bars) / len(bars) if bars else 0.0,
        }

    def _table_rows(self, start, end, group_by, spent):
        utc_start, utc_end = self._bounds(start, end)
        base = [('event_date', '>=', fields.Datetime.to_string(utc_start)),
                ('event_date', '<', fields.Datetime.to_string(utc_end))] + self._source_domain()
        fetched = self._rows(start, end, group_by)
        names = {}
        if group_by == 'country':
            ids = [r[0] for r in fetched if r[0]]
            names = {c.id: c.name for c in self.env['res.country'].browse(ids)}
        elif group_by == 'contact':
            ids = [r[0] for r in fetched if r[0]]
            names = {p.id: p.display_name
                     for p in self.env['res.partner'].sudo().browse(ids).exists()}
        top = max((r[-4] for r in fetched), default=0.0)
        rows = []
        for record in fetched:
            keys, (qty, free, cost, unit, units, count) = record[:-6], record[-6:]
            channel = False
            if group_by == 'category':
                channel, category = keys
                label = self._category_label(category)
                domain = [('channel', '=', channel), ('category', '=', category)]
            elif group_by == 'campaign':
                label = keys[0] or _('No campaign')
                domain = [('campaign_id', '=', keys[0] or False)]
            elif group_by == 'account':
                channel = keys[0]
                label = keys[1] or _('Not recorded')
                domain = [('channel', '=', channel), ('account_ref', '=', keys[1] or False)]
            elif group_by == 'source':
                label = self._source_label(keys[0])
                if keys[1]:
                    label = '%s: %s' % (label, self._feature_label(keys[1]))
                domain = [('source', 'in', [False, 'other']) if keys[0] in (None, 'other')
                          else ('source', '=', keys[0]), ('feature', '=', keys[1] or False)]
            elif group_by == 'country':
                label = names.get(keys[0]) or _('Unknown country')
                domain = [('country_id', '=', keys[0] or False)]
            else:
                label = names.get(keys[0]) or _('No contact')
                domain = [('partner_id', '=', keys[0] or False)]
            mixed = units > 1
            paid = qty - free
            rows.append({
                'key': '/'.join(str(k) for k in keys),
                'channel': channel,
                'channel_label': self._channel_label(channel) if channel else '',
                'label': label,
                # Mixed units (messages + minutes) cannot be added up: show events.
                'qty': count if mixed else qty,
                'unit': _('charges') if mixed else self._unit_label(unit),
                'free': None if mixed else free,
                'rate': cost / paid if not mixed and paid > 0 and cost else None,
                'cost': cost,
                'share': round(cost / spent * 100) if spent else 0,
                'bar': round(cost / top * 100) if top else 0,
                'domain': base + domain,
            })
        return rows

    # ------------------------------------------------------------------
    # For other apps' dashboards
    # ------------------------------------------------------------------
    @api.model
    def budget_warnings(self):
        """This month's budget warnings, newest first, for other apps to show.
        Empty for a user without billing access."""
        if not self.env['comm.billing.event'].has_access('read'):
            return []
        budget = self.env['comm.billing.budget']._for_company()
        if not budget:
            return []
        alerts = self.env['comm.billing.budget.alert'].sudo().search(
            [('budget_id', '=', budget.id), ('month', '=', self._today().replace(day=1))],
            order='id desc')
        return [{'key': alert.id, 'text': alert.name,
                 'at': fields.Datetime.to_string(alert.create_date)} for alert in alerts]

    @api.model
    def dashboard_cost(self, source, since):
        """What `source` has cost since `since` (a UTC datetime), for a tile on
        another app's dashboard. False for a user without billing access, so
        the tile simply does not show for them."""
        if source not in SOURCES or not self.env['comm.billing.event'].has_access('read'):
            return False
        self = self.with_context(billing_source=source)
        since = fields.Datetime.to_datetime(since)
        today = self._today()
        start = pytz.utc.localize(since).astimezone(self._tz()).date()
        by_channel = self._by_channel(start, today)
        channels = sorted(
            ({'key': channel, 'label': self._channel_label(channel), 'cost': values['cost']}
             for channel, values in by_channel.items() if values['cost']),
            key=lambda c: -c['cost'])
        utc_start, _utc_end = self._bounds(start, today)
        self.env.cr.execute(f"""
            SELECT e.feature, {self._cost_sql()}
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s {self._source_sql()}
               AND e.feature IS NOT NULL
             GROUP BY e.feature
        """, self._params(start, today))
        features = sorted(
            ({'key': feature, 'label': self._feature_label(feature), 'cost': cost}
             for feature, cost in self.env.cr.fetchall() if cost),
            key=lambda f: -f['cost'])
        return {
            'currency_id': self.env.company.currency_id.id,
            'source': source,
            'total': sum(c['cost'] for c in channels),
            'channels': channels,
            # What it was spent on, where the sender said: job alerts, the Sidekick...
            'features': features,
            'warnings': self.budget_warnings(),
            'unpriced': sum(v['unpriced'] for v in by_channel.values()),
            'date_from': str(start),
            'date_to': str(today),
        }

    # ------------------------------------------------------------------
    # Monthly statement
    # ------------------------------------------------------------------
    @api.model
    def statement(self, month=None):
        """Everything on the statement for `month` ('YYYY-MM'; default last month)."""
        self.env['comm.billing.event'].check_access('read')
        today = self._today()
        try:
            year, mon = (int(part) for part in (month or '').split('-'))
            first = date(year, mon, 1)
        except ValueError:
            first = today.replace(day=1) - relativedelta(months=1)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        closed = last < today
        end = last if closed else today
        p_first = first - relativedelta(months=1)
        p_last = first - timedelta(days=1)
        currency = self.env.company.currency_id

        self.env.cr.execute(f"""
            SELECT e.channel, COALESCE(e.provider, ''), e.category, MIN(e.unit),
                   SUM(e.unit_qty),
                   COALESCE(SUM(e.unit_qty) FILTER (WHERE e.is_free), 0),
                   {self._cost_sql()}
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s
             GROUP BY e.channel, COALESCE(e.provider, ''), e.category
             ORDER BY 7 DESC
        """, self._params(first, end))
        sections = {}
        for channel, provider, category, unit, qty, free, cost in self.env.cr.fetchall():
            section = sections.setdefault((channel, provider), {
                'key': '%s/%s' % (channel, provider),
                'channel': channel,
                'label': self._channel_label(channel),
                'provider': provider,
                'total': 0.0,
                'lines': [],
            })
            section['total'] += cost
            paid = qty - free
            if paid > 0 or not free:
                section['lines'].append({
                    'label': self._category_label(category),
                    'qty': paid, 'unit': self._unit_label(unit),
                    'rate': cost / paid if paid > 0 and cost else None,
                    'free': False, 'cost': cost,
                })
            if free:
                section['lines'].append({
                    'label': _('%s, sent for free', self._category_label(category)),
                    'qty': free, 'unit': self._unit_label(unit),
                    'rate': None, 'free': True, 'cost': 0.0,
                })
        sections = sorted(sections.values(), key=lambda s: -s['total'])
        total = sum(s['total'] for s in sections)

        # Our records against what each provider invoiced.
        ours = {}
        for section in sections:
            name = section['provider'] or section['label']
            ours[name] = ours.get(name, 0.0) + section['total']
        invoices = {
            inv.provider: inv for inv in self.env['comm.billing.invoice'].search([
                ('month', '=', first), ('company_id', '=', self.env.company.id)])
        }
        checks = []
        for name in list(ours) + [p for p in invoices if p not in ours]:
            mine = ours.get(name, 0.0)
            invoice = invoices.get(name)
            if not invoice:
                checks.append({'provider': name, 'ours': mine, 'theirs': None,
                               'diff': None, 'pct': None, 'result': 'missing'})
                continue
            diff = invoice.amount - mine
            pct = abs(diff) / invoice.amount * 100 if invoice.amount else (100.0 if diff else 0.0)
            checks.append({
                'provider': name, 'ours': mine, 'theirs': invoice.amount,
                'diff': diff, 'pct': round(pct, 1),
                'result': ('match' if currency.is_zero(diff)
                           else 'close' if pct <= 2 else 'differs'),
            })

        self.env.cr.execute("""
            SELECT COALESCE(e.provider, ''), ROUND(e.fx_rate::numeric, 4)
              FROM comm_billing_event e
             WHERE e.event_date >= %(start)s AND e.event_date < %(end)s
               AND e.price_usd > 0 AND e.currency_id = %(cur)s AND e.fx_rate <> 1
             GROUP BY 1, 2 ORDER BY 1, 2
        """, self._params(first, end))
        fx = {}
        for provider, rate in self.env.cr.fetchall():
            fx.setdefault(provider or _('Other'), []).append(float(rate))

        now = self._by_channel(first, end)
        budget = self.env['comm.billing.budget']._for_company()
        return {
            'currency_id': currency.id,
            'currency': currency.name,
            'month': '%04d-%02d' % (first.year, first.month),
            'month_label': format_date(self.env, first, date_format='MMMM y'),
            'span': self._span_label(first, end),
            'closed': closed,
            'total': total,
            'prev_label': format_date(self.env, p_first, date_format='MMMM'),
            'prev': sum(v['cost'] for v in self._by_channel(p_first, p_last).values()),
            'free_qty': sum(v['free_qty'] for v in now.values()),
            'unpriced': sum(v['unpriced'] for v in now.values()),
            'unconverted': sum(v['unconverted'] for v in now.values()),
            'budget': budget.amount if budget else 0.0,
            'sections': sections,
            'checks': checks,
            'fx': [{'provider': p, 'rates': rates} for p, rates in fx.items()],
            'domain': [('event_date', '>=', fields.Datetime.to_string(self._utc(first))),
                       ('event_date', '<', fields.Datetime.to_string(
                           self._utc(end + timedelta(days=1))))],
            'can_configure': self.env['comm.billing.invoice'].has_access('create'),
        }


class CommBillingStatementPdf(models.AbstractModel):
    _name = 'report.comm_billing_core.report_statement'
    _description = 'Communication monthly statement (PDF)'

    @api.model
    def _get_report_values(self, docids, data=None):
        statement = self.env['comm.billing.report'].statement((data or {}).get('month'))
        return {
            'doc_ids': docids,
            'doc_model': 'comm.billing.budget',
            'docs': self.env['comm.billing.budget'],
            'company': self.env.company,
            'currency': self.env.company.currency_id,
            's': statement,
            'today': format_date(self.env, fields.Date.context_today(self),
                                 date_format='d MMMM y'),
        }
