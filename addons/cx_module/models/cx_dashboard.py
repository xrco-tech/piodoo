# -*- coding: utf-8 -*-
"""UCX efficiency dashboards — one aggregation engine, three role scopes.

`get_metrics(scope, days, team)` returns a JSON-serialisable payload the OWL
dashboard renders as KPI cards, trend/distribution charts, a sentiment donut and
(for team/org) an agent leaderboard. It draws from the SAME reused Gen-2 ledger
as the Inbox and the pivot reports (comm.conversation / comm.interaction /
whatsapp.call.log) so nothing drifts.

Honesty of measures — this instance has no CSAT/rating capture and no SLA
contract model, so:
  * "Satisfaction" is the AI Copilot's sentiment (ai_sentiment), labelled as a
    proxy, not a surveyed CSAT.
  * "First-response SLA%" is measured against a CONFIGURABLE target
    (ir.config_parameter cx_module.first_response_target_secs, default 600s) —
    a self-defined threshold, not a contracted SLA.
  * Voice metrics are team/aggregate level: the call log routes to teams and does
    not store a single answering agent, so calls are not in the per-agent board.

Scope gating: 'me' is always the current user's own rows. 'team' and 'org'
expose cross-agent data and REQUIRE group_cx_manager — enforced here, server
side, regardless of what the client sends.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

DEFAULT_FR_TARGET_SECS = 600  # 10 minutes
MAX_DAYS = 365
DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
# First-response distribution buckets, in seconds (upper bound, None = overflow).
FR_BUCKETS = [
    ('0-10 min', 600),
    ('10-20 min', 1200),
    ('20-30 min', 1800),
    ('30-40 min', 2400),
    ('40-60 min', 3600),
    ('60+ min', None),
]


class CxDashboard(models.TransientModel):
    _name = 'cx.dashboard'
    _description = 'UCX Efficiency Dashboard engine'

    # ------------------------------------------------------------------ public
    @api.model
    def get_metrics(self, scope='me', days=30, team=None, filters=None,
                    date_from=None, date_to=None):
        """Aggregate efficiency metrics for the given scope + filters.

        scope:      'me' (own rows), 'team', 'org'.
        days:       quick look-back window in days (used when no custom range).
        date_from/date_to: 'YYYY-MM-DD' custom range (overrides `days`).
        team:       legacy single-team arg (folds into filters['teams']).
        filters:    {teams:[codes], agents:[ids], channels:[ids],
                     campaigns:[ids], direction:'inbound'|'outbound'}.
                    Cross-actor filters (agents/teams) are ignored on 'me'.
        """
        days = max(1, min(int(days or 30), MAX_DAYS))
        scope = scope if scope in ('me', 'team', 'org') else 'me'
        filters = dict(filters or {})
        if team and not filters.get('teams'):
            filters['teams'] = [team]

        is_manager = self.env.user.has_group('cx_module.group_cx_manager')
        if scope in ('team', 'org') and not is_manager:
            raise AccessError(
                "Team and organisation dashboards are limited to CX Managers.")
        if scope == 'me':                       # an agent only ever sees own rows
            filters.pop('agents', None)
            filters.pop('teams', None)
        if scope == 'team':                     # team dashboards don't slice by team
            filters.pop('teams', None)

        dt_from, dt_to, window_label = self._resolve_window(days, date_from, date_to)
        params = {'uid': self.env.uid, 'dt_from': dt_from, 'dt_to': dt_to}
        self._apply_filter_params(filters, params)
        where = self._build_where(scope, filters, windowed=True)
        where_live = self._build_where(scope, filters, windowed=False)
        target = self._fr_target_secs()
        currency = self.env.company.currency_id

        payload = {
            'scope': scope,
            'scope_label': {'me': 'My performance', 'team': 'Team',
                            'org': 'Organisation'}[scope],
            'days': days,
            'window_label': window_label,
            'date_from': date_from or '',
            'date_to': date_to or '',
            'sla_target_secs': target,
            'is_manager': is_manager,
            'currency': {'symbol': currency.symbol or currency.name,
                         'name': currency.name, 'position': currency.position},
            'filters': {'teams': filters.get('teams') or [],
                        'agents': filters.get('agents') or [],
                        'channels': filters.get('channels') or [],
                        'campaigns': filters.get('campaigns') or [],
                        'direction': filters.get('direction') or ''},
            'filter_options': self._filter_options(scope, params),
            'kpis': self._kpis(where, params, target),
            'trend': self._trend(where, params),
            'dow': self._dow(where, params),
            'fr_distribution': self._fr_distribution(where, params),
            'sentiment': self._sentiment(where, params),
            'leaderboard': self._leaderboard(where, params) if scope != 'me' else [],
        }
        # Omni-channel deep-dive: only on the Manager (org) dashboard, where the
        # cross-channel / queue / campaign / customer picture is the whole point.
        if scope == 'org':
            payload['omni'] = {
                'channels': self._omni_channels(where, params, currency),
                'queue': self._omni_queue(where_live, params),
                'campaigns': self._omni_campaigns(params, currency),
                'customers': self._omni_customers(where, params),
            }
        return payload

    # --------------------------------------------------------------- internals
    def _resolve_window(self, days, date_from, date_to):
        """Return (dt_from, dt_to, label). A valid custom range wins; otherwise
        the quick `days` look-back to now."""
        now = fields.Datetime.now()
        if date_from and date_to:
            try:
                d0 = fields.Date.to_date(date_from)
                d1 = fields.Date.to_date(date_to)
                if d0 and d1 and d0 <= d1:
                    dt_from = fields.Datetime.to_datetime(d0)
                    dt_to = fields.Datetime.to_datetime(d1) + timedelta(days=1)
                    return dt_from, dt_to, '%s → %s' % (date_from, date_to)
            except (ValueError, TypeError):
                pass
        return now - timedelta(days=days), now, 'last %s days' % days

    def _apply_filter_params(self, filters, params):
        if filters.get('teams'):
            params['f_teams'] = [str(t) for t in filters['teams']]
        if filters.get('agents'):
            params['f_agents'] = [int(a) for a in filters['agents']]
        if filters.get('channels'):
            params['f_channels'] = [int(c) for c in filters['channels']]
        if filters.get('campaigns'):
            # conversation.campaign_id is a Char holding str(campaign.id).
            params['f_campaigns'] = [str(int(c)) for c in filters['campaigns']]
        if filters.get('direction') in ('inbound', 'outbound'):
            params['f_direction'] = filters['direction']

    def _build_where(self, scope, filters, windowed=True):
        """Shared WHERE fragment on alias c = comm_conversation. `windowed`
        adds the date-window bound (omit it for the live queue)."""
        clauses = []
        if windowed:
            clauses.append("c.opened_at >= %(dt_from)s AND c.opened_at < %(dt_to)s")
        if scope == 'me':
            clauses.append("c.assigned_agent_id = %(uid)s")
        if filters.get('teams'):
            clauses.append("c.assigned_team_code = ANY(%(f_teams)s)")
        if filters.get('agents'):
            clauses.append("c.assigned_agent_id = ANY(%(f_agents)s)")
        if filters.get('channels'):
            clauses.append("c.primary_channel_id = ANY(%(f_channels)s)")
        if filters.get('campaigns'):
            clauses.append("c.campaign_id = ANY(%(f_campaigns)s)")
        if filters.get('direction') in ('inbound', 'outbound'):
            clauses.append(
                "(SELECT i2.direction FROM comm_interaction i2 "
                "WHERE i2.conversation_id = c.id ORDER BY i2.at LIMIT 1) = %(f_direction)s")
        return " AND ".join(clauses) if clauses else "TRUE"

    def _filter_options(self, scope, params):
        """Options for the filter bar. Channels + campaigns are global lists;
        agents/teams are the ones actually present in the current window."""
        opts = {'agents': [], 'channels': [], 'campaigns': [], 'teams': []}
        opts['channels'] = [
            {'id': c.id, 'name': c.name}
            for c in self.env['comm.channel'].sudo().search(
                [('active', '=', True)], order='sequence, code')]
        opts['campaigns'] = [
            {'id': c.id, 'name': c.name}
            for c in self.env['comm.campaign'].sudo().search(
                [], order='id desc', limit=50)]
        if scope in ('team', 'org'):
            self.env.cr.execute("""
                SELECT DISTINCT assigned_agent_id FROM comm_conversation
                 WHERE assigned_agent_id IS NOT NULL
                   AND opened_at >= %(dt_from)s AND opened_at < %(dt_to)s
            """, params)
            ids = [r[0] for r in self.env.cr.fetchall()]
            names = {u.id: u.name
                     for u in self.env['res.users'].sudo().browse(ids)}
            opts['agents'] = sorted(
                ({'id': i, 'name': names.get(i, '?')} for i in ids),
                key=lambda x: x['name'])
        if scope == 'org':
            self.env.cr.execute("""
                SELECT DISTINCT assigned_team_code FROM comm_conversation
                 WHERE assigned_team_code IS NOT NULL AND assigned_team_code != ''
                   AND opened_at >= %(dt_from)s AND opened_at < %(dt_to)s
                 ORDER BY 1
            """, params)
            opts['teams'] = [r[0] for r in self.env.cr.fetchall()]
        return opts

    def _to_company_currency(self, amount_usd, currency):
        """Convert a USD figure (billing is stored in USD) to the company
        currency for display."""
        if not amount_usd:
            return 0.0
        try:
            usd = self.env.ref('base.USD', raise_if_not_found=False)
            if usd and currency and usd != currency:
                return currency.round(usd._convert(
                    amount_usd, currency, self.env.company, fields.Date.today()))
        except Exception:  # pragma: no cover - never let FX break the dashboard
            _logger.warning('cx dashboard FX convert failed', exc_info=True)
        return round(amount_usd, 2)

    def _fr_target_secs(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'cx_module.first_response_target_secs')
        try:
            return max(1, int(raw)) if raw else DEFAULT_FR_TARGET_SECS
        except (TypeError, ValueError):
            return DEFAULT_FR_TARGET_SECS

    def _first_response_cte(self):
        """SQL fragment: per-conversation first-response seconds.

        first inbound -> first outbound after it. Reused by KPIs and the
        distribution. Returns rows (conversation_id, fr_secs) for conversations
        that got at least one agent/bot reply after the first customer message.
        """
        return """
            SELECT i.conversation_id,
                   EXTRACT(EPOCH FROM (
                       MIN(i.at) FILTER (WHERE i.direction = 'outbound'
                                         AND i.at >= fin.first_in)
                       - fin.first_in))::float AS fr_secs
              FROM comm_interaction i
              JOIN (
                   SELECT conversation_id, MIN(at) AS first_in
                     FROM comm_interaction
                    WHERE direction = 'inbound'
                    GROUP BY conversation_id
              ) fin ON fin.conversation_id = i.conversation_id
             GROUP BY i.conversation_id, fin.first_in
        """

    def _kpis(self, where, params, target):
        self.env.cr.execute(f"""
            SELECT
                count(*)                                                   AS conversations,
                count(*) FILTER (WHERE c.lifecycle_state IN ('open','waiting','handoff')) AS open,
                count(*) FILTER (WHERE c.lifecycle_state = 'closed')       AS closed,
                count(*) FILTER (WHERE c.lifecycle_state = 'timeout')      AS timed_out,
                avg(EXTRACT(EPOCH FROM (c.closed_at - c.opened_at)))
                    FILTER (WHERE c.closed_at IS NOT NULL)                 AS avg_handle_secs
              FROM comm_conversation c
             WHERE {where}
        """, {**params, 'uid': self.env.uid})
        row = self.env.cr.dictfetchone() or {}

        # Message volume in-window.
        self.env.cr.execute(f"""
            SELECT count(i.id) AS messages
              FROM comm_interaction i
              JOIN comm_conversation c ON c.id = i.conversation_id
             WHERE {where}
        """, {**params, 'uid': self.env.uid})
        messages = (self.env.cr.dictfetchone() or {}).get('messages') or 0

        # First-response average + SLA% against target.
        self.env.cr.execute(f"""
            WITH fr AS ({self._first_response_cte()})
            SELECT avg(fr.fr_secs)                                          AS avg_fr,
                   count(*)                                                 AS answered,
                   count(*) FILTER (WHERE fr.fr_secs <= %(target)s)         AS within
              FROM fr
              JOIN comm_conversation c ON c.id = fr.conversation_id
             WHERE fr.fr_secs IS NOT NULL AND fr.fr_secs >= 0 AND {where}
        """, {**params, 'uid': self.env.uid, 'target': target})
        fr = self.env.cr.dictfetchone() or {}
        answered = fr.get('answered') or 0
        sla_pct = round(100.0 * (fr.get('within') or 0) / answered, 1) if answered else None

        # Voice (team/aggregate). Skipped for scope='me' where the board hides it,
        # but harmless to compute — filtered by call team when a team is set.
        voice = self._voice(params)

        return {
            'conversations': row.get('conversations') or 0,
            'open': row.get('open') or 0,
            'closed': row.get('closed') or 0,
            'timed_out': row.get('timed_out') or 0,
            'avg_handle_secs': self._round(row.get('avg_handle_secs')),
            'avg_first_response_secs': self._round(fr.get('avg_fr')),
            'first_response_sla_pct': sla_pct,
            'messages': messages,
            'calls_answered': voice['answered'],
            'calls_missed': voice['missed'],
            'avg_call_secs': voice['avg_secs'],
        }

    def _voice(self, params):
        # Call log has no per-agent field; window by call_timestamp only.
        self.env.cr.execute("""
            SELECT
                count(*) FILTER (WHERE call_status = 'answered' OR (call_status = 'ended' AND duration > 0)) AS answered,
                count(*) FILTER (WHERE is_missed) AS missed,
                avg(duration) FILTER (WHERE duration > 0) AS avg_secs
              FROM whatsapp_call_log
             WHERE call_timestamp >= %(dt_from)s AND call_timestamp < %(dt_to)s
        """, {'dt_from': params['dt_from'], 'dt_to': params['dt_to']})
        row = self.env.cr.dictfetchone() or {}
        return {
            'answered': row.get('answered') or 0,
            'missed': row.get('missed') or 0,
            'avg_secs': self._round(row.get('avg_secs')),
        }

    def _trend(self, where, params):
        self.env.cr.execute(f"""
            SELECT to_char(date_trunc('day', c.opened_at), 'YYYY-MM-DD') AS day,
                   count(*) AS opened,
                   count(*) FILTER (WHERE c.closed_at IS NOT NULL
                        AND date_trunc('day', c.closed_at) = date_trunc('day', c.opened_at)) AS closed
              FROM comm_conversation c
             WHERE {where}
             GROUP BY 1
             ORDER BY 1
        """, {**params, 'uid': self.env.uid})
        return [{'day': r[0], 'opened': r[1], 'closed': r[2]}
                for r in self.env.cr.fetchall()]

    def _dow(self, where, params):
        self.env.cr.execute(f"""
            SELECT EXTRACT(ISODOW FROM c.opened_at)::int AS dow, count(*) AS n
              FROM comm_conversation c
             WHERE {where}
             GROUP BY 1
        """, {**params, 'uid': self.env.uid})
        counts = {r[0]: r[1] for r in self.env.cr.fetchall()}
        return [{'dow': i + 1, 'label': DOW_LABELS[i], 'opened': counts.get(i + 1, 0)}
                for i in range(7)]

    def _fr_distribution(self, where, params):
        self.env.cr.execute(f"""
            WITH fr AS ({self._first_response_cte()})
            SELECT fr.fr_secs
              FROM fr
              JOIN comm_conversation c ON c.id = fr.conversation_id
             WHERE fr.fr_secs IS NOT NULL AND fr.fr_secs >= 0 AND {where}
        """, {**params, 'uid': self.env.uid})
        secs = [r[0] for r in self.env.cr.fetchall()]
        total = len(secs) or 1
        out = []
        lower = 0
        for label, upper in FR_BUCKETS:
            if upper is None:
                n = sum(1 for s in secs if s >= lower)
            else:
                n = sum(1 for s in secs if lower <= s < upper)
                lower = upper
            out.append({'bucket': label, 'count': n,
                        'pct': round(100.0 * n / total, 0)})
        return out

    def _sentiment(self, where, params):
        self.env.cr.execute(f"""
            SELECT coalesce(c.ai_sentiment, 'unrated') AS s, count(*) AS n
              FROM comm_conversation c
             WHERE {where}
             GROUP BY 1
        """, {**params, 'uid': self.env.uid})
        counts = {r[0]: r[1] for r in self.env.cr.fetchall()}
        return {k: counts.get(k, 0)
                for k in ('positive', 'neutral', 'negative', 'unrated')}

    def _leaderboard(self, where, params):
        self.env.cr.execute(f"""
            WITH fr AS ({self._first_response_cte()}),
            base AS (
                SELECT c.id, c.assigned_agent_id, c.lifecycle_state, c.ai_sentiment,
                       EXTRACT(EPOCH FROM (c.closed_at - c.opened_at)) AS handle_secs,
                       (SELECT count(*) FROM comm_interaction i WHERE i.conversation_id = c.id) AS msgs,
                       f.fr_secs
                  FROM comm_conversation c
                  LEFT JOIN fr f ON f.conversation_id = c.id
                 WHERE c.assigned_agent_id IS NOT NULL AND {where}
            )
            SELECT b.assigned_agent_id AS agent_id,
                   count(*)                                                    AS conversations,
                   count(*) FILTER (WHERE b.lifecycle_state = 'closed')        AS closed,
                   avg(b.handle_secs) FILTER (WHERE b.handle_secs IS NOT NULL) AS avg_handle,
                   avg(b.fr_secs) FILTER (WHERE b.fr_secs IS NOT NULL AND b.fr_secs >= 0) AS avg_fr,
                   sum(b.msgs)                                                 AS messages,
                   count(*) FILTER (WHERE b.ai_sentiment = 'positive')         AS pos,
                   count(*) FILTER (WHERE b.ai_sentiment = 'negative')         AS neg
              FROM base b
             GROUP BY b.assigned_agent_id
             ORDER BY conversations DESC
             LIMIT 25
        """, {**params, 'uid': self.env.uid})
        rows = self.env.cr.dictfetchall()
        agent_ids = [r['agent_id'] for r in rows]
        names = {u.id: u.name
                 for u in self.env['res.users'].sudo().browse(agent_ids)}
        board = []
        for r in rows:
            rated = (r['pos'] or 0) + (r['neg'] or 0)
            score = round(100.0 * (r['pos'] or 0) / rated, 0) if rated else None
            board.append({
                'agent_id': r['agent_id'],
                'agent': names.get(r['agent_id'], 'Unknown'),
                'conversations': r['conversations'] or 0,
                'closed': r['closed'] or 0,
                'avg_handle_secs': self._round(r['avg_handle']),
                'avg_first_response_secs': self._round(r['avg_fr']),
                'messages': r['messages'] or 0,
                'sentiment_score': score,
            })
        return board

    # ------------------------------------------------------- omni-channel (org)
    def _omni_channels(self, where, params, currency):
        """Per-channel mix: conversations (by the conversation's primary channel)
        merged with messages + cost (by each interaction's own channel). This is
        the module's omni-channel headline — one row per channel. Cost is
        converted from stored USD into the company currency."""
        p = {**params, 'uid': self.env.uid}
        self.env.cr.execute(f"""
            SELECT ch.id AS cid, ch.code AS code, ch.name AS name, count(c.id) AS convos
              FROM comm_conversation c
              JOIN comm_channel ch ON ch.id = c.primary_channel_id
             WHERE {where}
             GROUP BY ch.id, ch.code, ch.name
        """, p)
        by_id = {r['cid']: {'channel_id': r['cid'], 'code': r['code'],
                            'name': r['name'], 'conversations': r['convos'],
                            'messages': 0, 'cost': 0.0}
                 for r in self.env.cr.dictfetchall()}
        self.env.cr.execute(f"""
            SELECT ch.id AS cid, ch.code AS code, ch.name AS name,
                   count(i.id) AS msgs,
                   coalesce(sum(i.projected_cost_usd), 0)::float AS cost
              FROM comm_interaction i
              JOIN comm_conversation c ON c.id = i.conversation_id
              JOIN comm_channel ch ON ch.id = i.channel_id
             WHERE {where}
             GROUP BY ch.id, ch.code, ch.name
        """, p)
        for r in self.env.cr.dictfetchall():
            row = by_id.setdefault(r['cid'], {
                'channel_id': r['cid'], 'code': r['code'], 'name': r['name'],
                'conversations': 0, 'messages': 0, 'cost': 0.0})
            row['messages'] = r['msgs']
            row['cost'] = self._to_company_currency(r['cost'], currency)
        rows = sorted(by_id.values(),
                      key=lambda x: (x['conversations'], x['messages']), reverse=True)
        return rows

    def _omni_queue(self, where_live, params):
        """Live backlog RIGHT NOW (not window-bounded, but respecting the active
        team/agent/channel/campaign/direction filters) by channel."""
        self.env.cr.execute(f"""
            SELECT coalesce(ch.name, '—') AS channel,
                   count(*) AS waiting,
                   EXTRACT(EPOCH FROM ((now() at time zone 'UTC') - min(c.opened_at)))::int AS oldest_secs
              FROM comm_conversation c
              LEFT JOIN comm_channel ch ON ch.id = c.primary_channel_id
             WHERE c.lifecycle_state IN ('open', 'waiting', 'handoff') AND {where_live}
             GROUP BY ch.name
             ORDER BY waiting DESC
        """, {**params, 'uid': self.env.uid})
        rows = [{'channel': r[0], 'waiting': r[1], 'oldest_secs': r[2] or 0}
                for r in self.env.cr.fetchall()]
        total = sum(r['waiting'] for r in rows)
        oldest = max((r['oldest_secs'] for r in rows), default=0)
        return {'rows': rows, 'total_waiting': total, 'oldest_secs': oldest}

    def _omni_campaigns(self, params, currency):
        """Recent campaigns (performance from the send ledger) + cross-channel
        reach — the omni-channel spread of outbound sends in-window. Cost is
        converted from stored USD into the company currency."""
        camps = self.env['comm.campaign'].sudo().search([], order='id desc', limit=8)
        clist = [{
            'id': c.id, 'name': c.name, 'state': c.state,
            'sends': c.total_sends, 'delivered': c.successful_sends,
            'conversions': c.conversion_count,
            'cost': self._to_company_currency(c.total_cost_usd or 0.0, currency),
        } for c in camps]
        # Sends by channel (omni-channel reach) over the window.
        self.env.cr.execute("""
            SELECT coalesce(ch.name, '—') AS channel, count(*) AS sends
              FROM comm_campaign_send s
              LEFT JOIN comm_channel ch ON ch.id = s.chosen_channel_id
             WHERE coalesce(s.sent_at, s.scheduled_at, s.create_date)
                   >= %(dt_from)s
               AND coalesce(s.sent_at, s.scheduled_at, s.create_date) < %(dt_to)s
             GROUP BY ch.name
             ORDER BY sends DESC
        """, {'dt_from': params['dt_from'], 'dt_to': params['dt_to']})
        by_channel = [{'channel': r[0], 'sends': r[1]}
                      for r in self.env.cr.fetchall()]
        return {'list': clist, 'by_channel': by_channel}

    def _omni_customers(self, where, params):
        """Customer reach with an omni-channel lens: how many customers we touch,
        how many we reach on MORE THAN ONE channel, new vs returning, and the top
        customers by volume with their channel spread."""
        p = {**params, 'uid': self.env.uid}
        self.env.cr.execute(f"""
            WITH active AS (
                SELECT c.partner_id,
                       count(*) AS convos,
                       count(DISTINCT c.primary_channel_id) AS channels
                  FROM comm_conversation c
                 WHERE {where} AND c.partner_id IS NOT NULL
                 GROUP BY c.partner_id
            ),
            firstseen AS (
                SELECT partner_id, min(opened_at) AS first_ever
                  FROM comm_conversation
                 GROUP BY partner_id
            )
            SELECT a.partner_id, a.convos, a.channels,
                   (f.first_ever >= %(dt_from)s) AS is_new
              FROM active a
              JOIN firstseen f ON f.partner_id = a.partner_id
             ORDER BY a.convos DESC
        """, p)
        rows = self.env.cr.dictfetchall()
        total = len(rows)
        multi = sum(1 for r in rows if (r['channels'] or 0) > 1)
        new = sum(1 for r in rows if r['is_new'])
        top_rows = rows[:8]
        names = {pr.id: pr.name for pr in
                 self.env['res.partner'].sudo().browse([r['partner_id'] for r in top_rows])}
        top = [{'partner_id': r['partner_id'],
                'name': names.get(r['partner_id'], 'Unknown'),
                'conversations': r['convos'], 'channels': r['channels']}
               for r in top_rows]
        return {'total': total, 'multi_channel': multi,
                'new': new, 'returning': total - new, 'top': top}

    @staticmethod
    def _round(v):
        return round(float(v), 1) if v is not None else None
