# -*- coding: utf-8 -*-
"""What the Sediba workspace screen reads: one `ws_*` call per page, no tables.

Everything is read as the signed-in user, so the researcher group decides who
gets in. The two writes (status and the review flag) go through the finding's
own rules.
"""
from odoo import api, fields, models
from odoo.tools import format_date

from .sediba import SOURCE_KINDS, STATUSES, STRONG_KINDS

DATE_FORMAT = 'd MMM y'
# What is proven comes first on a topic's board.
BOARD_ORDER = ('verified', 'lead', 'unconfirmed')


class SedibaWorkspace(models.AbstractModel):
    _name = 'sediba.workspace'
    _description = 'Sediba workspace'

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _date(self, value):
        return format_date(self.env, value, date_format=DATE_FORMAT) if value else False

    @api.model
    def _next_topic(self):
        """The topic to research next: the first never researched, else the
        one due soonest. The scheduled agent follows the same rule."""
        topics = self.env['sediba.topic'].search([])
        never = topics.filtered(lambda t: not t.last_researched)
        if never:
            return never[0]
        return topics.sorted(lambda t: (t.due_date or fields.Date.today(), t.sequence, t.id))[:1]

    def _topic_row(self, topic, next_topic):
        return {
            'id': topic.id,
            'name': topic.name,
            'last': self._date(topic.last_researched),
            'due': self._date(topic.due_date),
            'verified': topic.verified_count,
            'leads': topic.lead_count,
            'unconfirmed': topic.unconfirmed_count,
            'next': topic == next_topic,
        }

    def _finding_row(self, finding):
        return {
            'id': finding.id,
            'name': finding.name,
            'statement': finding.statement or '',
            'status': finding.status,
            'sources': finding.source_summary or '',
            'checked': self._date(finding.checked_on),
            'disagree': finding.sources_disagree,
            'review': finding.needs_review,
            'review_note': finding.review_note or '',
            'topic': [finding.topic_id.id, finding.topic_id.name],
        }

    def _run_row(self, run):
        return {
            'id': run.id,
            'date': self._date(run.run_date),
            'topic': [run.topic_id.id, run.topic_id.name],
            'researcher': run.researcher or '',
            'summary': run.summary or '',
            'failures': run.failures or '',
            'verified': run.verified_count,
            'leads': run.lead_count,
            'unconfirmed': run.unconfirmed_count,
        }

    def _evidence(self, finding):
        """In words: how many opened sources of each kind, strongest first."""
        opened = finding.source_ids.filtered('opened')
        labels = dict(SOURCE_KINDS)
        parts = []
        for kind, _label in SOURCE_KINDS:
            count = len(opened.filtered(lambda s: s.kind == kind))
            if count:
                parts.append({'kind': kind, 'label': labels[kind], 'count': count,
                              'strong': kind in STRONG_KINDS})
        return {'parts': parts, 'unopened': len(finding.source_ids) - len(opened)}

    # ── Reads ────────────────────────────────────────────────────────────────

    @api.model
    def ws_nav(self):
        Finding = self.env['sediba.finding']
        next_topic = self._next_topic()
        return {
            'topics': [self._topic_row(t, next_topic) for t in self.env['sediba.topic'].search([])],
            'all': Finding.search_count([]),
            'review': Finding.search_count([('needs_review', '=', True)]),
            'runs': self.env['sediba.run'].search_count([]),
        }

    @api.model
    def ws_overview(self):
        Finding = self.env['sediba.finding']
        next_topic = self._next_topic()
        last_run = self.env['sediba.run'].search([], limit=1)
        counts = {key: Finding.search_count([('status', '=', key)]) for key, _label in STATUSES}
        counts['review'] = Finding.search_count([('needs_review', '=', True)])
        return {
            'counts': counts,
            'last_run': self._run_row(last_run) if last_run else False,
            'next': {
                'id': next_topic.id,
                'name': next_topic.name,
                'scope': next_topic.scope or '',
                'due': self._date(next_topic.due_date),
                'leads': next_topic.lead_count,
            } if next_topic else False,
            'review': [self._finding_row(f) for f in Finding.search([('needs_review', '=', True)], limit=20)],
            'topics': [self._topic_row(t, next_topic) for t in self.env['sediba.topic'].search([])],
        }

    @api.model
    def ws_topic(self, topic_id, search=''):
        topic = self.env['sediba.topic'].browse(topic_id).exists()
        if not topic:
            return False
        domain = [('topic_id', '=', topic.id)]
        if search:
            domain += ['|', ('name', 'ilike', search), ('statement', 'ilike', search)]
        findings = self.env['sediba.finding'].search(domain)
        topics = self.env['sediba.topic'].search([])
        return {
            'id': topic.id,
            'name': topic.name,
            'position': (topics.ids.index(topic.id) + 1) if topic.id in topics.ids else 0,
            'of': len(topics),
            'scope': topic.scope or '',
            'summary': [line.strip() for line in (topic.summary or '').splitlines() if line.strip()],
            'our_read': topic.our_read or '',
            'last': self._date(topic.last_researched),
            'due': self._date(topic.due_date),
            'columns': [{
                'key': key,
                'label': label,
                'findings': [self._finding_row(f) for f in findings.filtered(lambda f, k=key: f.status == k)],
            } for key, label in sorted(STATUSES, key=lambda item: BOARD_ORDER.index(item[0]))],
            'runs': [self._run_row(r) for r in self.env['sediba.run'].search([('topic_id', '=', topic.id)], limit=10)],
        }

    @api.model
    def ws_finding(self, finding_id):
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if not finding:
            return False
        labels = dict(SOURCE_KINDS)
        row = self._finding_row(finding)
        row.update({
            'why': finding.why_it_matters or '',
            'orgs': finding.organisation_ids.mapped('name'),
            'checked_by': finding.checked_by or '',
            'recheck': self._date(finding.recheck_by),
            'used_in': finding.used_in or '',
            'origin': finding.origin or '',
            'ref': finding.ref or '',
            'evidence': self._evidence(finding),
            'run': self._run_row(finding.run_id) if finding.run_id else False,
            'created': self._date(finding.create_date),
            'changed': self._date(finding.write_date),
            'changed_by': finding.write_uid.name or '',
            'source_rows': [{
                'id': s.id,
                'name': s.name,
                'url': s.url or '',
                'says': s.says or '',
                'figure_date': s.figure_date or '',
                'kind': labels.get(s.kind, ''),
                'opened': s.opened,
            } for s in finding.source_ids],
        })
        return row

    @api.model
    def ws_findings(self, pill='all', search='', offset=0, limit=40):
        domain = []
        if pill == 'review':
            domain.append(('needs_review', '=', True))
        elif pill in ('verified', 'lead', 'unconfirmed'):
            domain.append(('status', '=', pill))
        if search:
            domain += ['|', ('name', 'ilike', search), ('statement', 'ilike', search)]
        Finding = self.env['sediba.finding']
        return {
            'total': Finding.search_count(domain),
            'rows': [self._finding_row(f) for f in Finding.search(domain, offset=offset, limit=limit)],
        }

    @api.model
    def ws_runs(self, offset=0, limit=40):
        Run = self.env['sediba.run']
        return {
            'total': Run.search_count([]),
            'rows': [self._run_row(r) for r in Run.search([], offset=offset, limit=limit)],
        }

    # ── Writes ───────────────────────────────────────────────────────────────

    @api.model
    def ws_set_status(self, finding_id, status):
        """Move a finding between columns. Marking it verified or could not
        confirm records who looked and when; the finding's own rule still
        decides whether verified is allowed."""
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if not finding or status not in dict(STATUSES):
            return False
        vals = {'status': status}
        if status in ('verified', 'unconfirmed'):
            vals.update({'checked_on': fields.Date.context_today(self), 'checked_by': self.env.user.name})
        finding.write(vals)
        return self.ws_finding(finding.id)

    @api.model
    def ws_set_review(self, finding_id, needs_review):
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if not finding:
            return False
        finding.needs_review = bool(needs_review)
        return self.ws_finding(finding.id)
