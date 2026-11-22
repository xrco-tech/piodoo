# -*- coding: utf-8 -*-
"""What the Sediba workspace screen reads: one `ws_*` call per page, no tables.

Everything is read as the signed-in user, so the researcher group decides who
gets in. The two writes (status and the review flag) go through the finding's
own rules.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError
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
    def _topics(self, space=False):
        """Every topic. From inside an app (by its key): only the topics shown
        in that app that have something verified to show."""
        if not space:
            return self.env['sediba.topic'].search([])
        return self.env['sediba.topic'].search([
            ('space_ids.code', '=', space), ('finding_ids.status', '=', 'verified')])

    @api.model
    def _in_space(self, space=False):
        """A domain on findings: everything, or from inside an app only what
        is verified on that app's topics. Leads never show in an app."""
        if not space:
            return []
        return [('topic_id.space_ids.code', '=', space), ('status', '=', 'verified')]

    def _reference(self, row):
        """A finding as an app shows it: no review flag, no working notes."""
        row.update({'review': False, 'review_note': ''})
        return row

    @api.model
    def _next_topic(self):
        """The topic to research next: the first never researched, else the
        one due soonest. The scheduled agent follows the same rule."""
        topics = self._topics()
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
    # Each takes `space`: an app's key when the screen is opened from inside
    # that app as its Reference. Then only verified findings on that app's
    # topics show, with no leads, runs, review flags or interpretation, and
    # nothing can be changed.

    @api.model
    def ws_nav(self, space=False):
        Finding = self.env['sediba.finding']
        scope = self._in_space(space)
        next_topic = self.env['sediba.topic'] if space else self._next_topic()
        area = self.env['sediba.space'].search([('code', '=', space)], limit=1) if space else False
        return {
            'topics': [self._topic_row(t, next_topic) for t in self._topics(space)],
            'all': Finding.search_count(scope),
            'review': 0 if space else Finding.search_count([('needs_review', '=', True)]),
            'runs': 0 if space else self.env['sediba.run'].search_count([]),
            'space': area.name if area else False,
            'reference': bool(space),
            'can_edit': not space and self.env.user.has_group('sediba.group_user'),
        }

    @api.model
    def ws_overview(self, space=False):
        Finding = self.env['sediba.finding']
        if space:
            return {
                'counts': {'verified': Finding.search_count(self._in_space(space)), 'lead': 0, 'unconfirmed': 0, 'review': 0},
                'last_run': False,
                'next': False,
                'review': [],
                'topics': [self._topic_row(t, self.env['sediba.topic']) for t in self._topics(space)],
            }
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
            'topics': [self._topic_row(t, next_topic) for t in self._topics()],
        }

    @api.model
    def ws_topic(self, topic_id, search='', space=False):
        topics = self._topics(space)
        topic = self.env['sediba.topic'].browse(topic_id).exists() & topics
        if not topic:
            return False
        domain = [('topic_id', '=', topic.id)] + self._in_space(space)
        if search:
            domain += ['|', ('name', 'ilike', search), ('statement', 'ilike', search)]
        findings = self.env['sediba.finding'].search(domain)
        statuses = [item for item in STATUSES if not space or item[0] == 'verified']
        row = self._reference if space else (lambda r: r)
        return {
            'id': topic.id,
            'name': topic.name,
            'position': topics.ids.index(topic.id) + 1,
            'of': len(topics),
            'scope': topic.scope or '',
            'summary': [line.strip() for line in (topic.summary or '').splitlines() if line.strip()],
            'our_read': '' if space else (topic.our_read or ''),
            # The same knowledge as blocks, drawn from facts on verified findings.
            'visual': topic._visual(),
            'last': self._date(topic.last_researched),
            'due': False if space else self._date(topic.due_date),
            'ai_allowed': False if space else topic.ai_allowed,
            'public_allowed': False if space else topic.public_allowed,
            'columns': [{
                'key': key,
                'label': label,
                'findings': [row(self._finding_row(f)) for f in findings.filtered(lambda f, k=key: f.status == k)],
            } for key, label in sorted(statuses, key=lambda item: BOARD_ORDER.index(item[0]))],
            'runs': [] if space else [
                self._run_row(r) for r in self.env['sediba.run'].search([('topic_id', '=', topic.id)], limit=10)],
        }

    @api.model
    def ws_finding(self, finding_id, space=False):
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if space:
            finding = finding.filtered_domain(self._in_space(space))
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
            'facts': [fact._text() for fact in finding.fact_ids],
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
        if space:
            self._reference(row)
            row.update({'run': False, 'origin': '', 'used_in': '', 'changed_by': ''})
        return row

    @api.model
    def ws_findings(self, pill='all', search='', offset=0, limit=40, space=False):
        domain = self._in_space(space)
        if space:
            pass  # verified only, whatever was asked for
        elif pill == 'review':
            domain.append(('needs_review', '=', True))
        elif pill in ('verified', 'lead', 'unconfirmed'):
            domain.append(('status', '=', pill))
        if search:
            domain += ['|', ('name', 'ilike', search), ('statement', 'ilike', search)]
        Finding = self.env['sediba.finding']
        row = self._reference if space else (lambda r: r)
        return {
            'total': Finding.search_count(domain),
            'rows': [row(self._finding_row(f)) for f in Finding.search(domain, offset=offset, limit=limit)],
        }

    @api.model
    def ws_runs(self, offset=0, limit=40, space=False):
        if space:
            return {'total': 0, 'rows': []}
        Run = self.env['sediba.run']
        return {
            'total': Run.search_count([]),
            'rows': [self._run_row(r) for r in Run.search([], offset=offset, limit=limit)],
        }

    # ── Writes ───────────────────────────────────────────────────────────────

    @api.model
    def ws_set_status(self, finding_id, status, space=False):
        """Move a finding between columns. Marking it verified or could not
        confirm records who looked and when; the finding's own rule still
        decides whether verified is allowed."""
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if space:
            raise AccessError(_("The Reference inside an app is read-only. Change findings in Sediba."))
        if not finding or status not in dict(STATUSES):
            return False
        vals = {'status': status}
        if status in ('verified', 'unconfirmed'):
            vals.update({'checked_on': fields.Date.context_today(self), 'checked_by': self.env.user.name})
        finding.write(vals)
        return self.ws_finding(finding.id, space)

    @api.model
    def ws_set_topic_ai(self, topic_id, allowed, space=False, public=False):
        """The two switches on a topic: may Sidekick answer from its verified
        findings, and (`public`) may a chatbot that talks to people outside
        the company."""
        if space:
            raise AccessError(_("The Reference inside an app is read-only. Change topics in Sediba."))
        topic = self.env['sediba.topic'].browse(topic_id).exists()
        if not topic:
            return False
        topic['public_allowed' if public else 'ai_allowed'] = bool(allowed)
        return self.ws_topic(topic.id)

    @api.model
    def ws_set_review(self, finding_id, needs_review, space=False):
        finding = self.env['sediba.finding'].browse(finding_id).exists()
        if space:
            raise AccessError(_("The Reference inside an app is read-only. Change findings in Sediba."))
        if not finding:
            return False
        finding.needs_review = bool(needs_review)
        return self.ws_finding(finding.id, space)
