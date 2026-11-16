# -*- coding: utf-8 -*-
"""What the Employers section of the workspace reads and saves.

Agents check each employer once. Nothing here blocks a job: a job from an
employer nobody has checked, or one marked not genuine, only carries a flag."""

from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.chat2work_jobs.models.chat2work_employer import CHECKS

from .chat2work_workspace import _dt

TO_CHECK = ('new', 'unsure')
PILLS = {'to_check': [('state', 'in', TO_CHECK)], 'verified': [('state', '=', 'verified')],
         'invalid': [('state', '=', 'invalid')], 'all': []}
JOBS_SHOWN = 30
HISTORY_SHOWN = 6


class Chat2workWorkspaceEmployers(models.AbstractModel):
    _inherit = 'chat2work.workspace'

    @api.model
    def ws_bootstrap(self):
        boot = super().ws_bootstrap()
        boot['employer_states'] = self._selection('chat2work.employer', 'state')
        return boot

    @api.model
    def ws_counts(self):
        counts = super().ws_counts()
        # Employers still to check that have at least one open job.
        counts['employers'] = self.env['chat2work.employer'].search_count(
            [('state', 'in', TO_CHECK), ('listing_ids.state', '=', 'open')])
        return counts

    def _employer(self, employer_id):
        employer = self.env['chat2work.employer'].browse(int(employer_id or 0)).exists()
        if not employer:
            raise UserError(_("This employer no longer exists. It may have been joined with another."))
        return employer

    def _employer_row(self, employer, open_count=None):
        return {
            'id': employer.id,
            'name': employer.name,
            'state': employer.state,
            'state_label': self._label(employer, 'state'),
            'recruiter': employer.is_recruiter,
            'jobs': employer.listing_count,
            'open': employer.open_count if open_count is None else open_count,
        }

    @api.model
    def ws_employers(self, pill='to_check', search='', offset=0, limit=None):
        """Employers for a filter, the ones with the most open jobs first."""
        self._check_agent()
        offset, limit = self._page(offset, limit)
        domain = list(PILLS.get(pill, PILLS['to_check']))
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('alias_ids.name', 'ilike', term)]
        Employer = self.env['chat2work.employer']
        ids = Employer.search(domain).ids
        if not ids:
            return []
        self.env['chat2work.listing'].flush_model()
        self.env.cr.execute("""
            SELECT e.id, COUNT(l.id) FILTER (WHERE l.state = 'open' AND l.active)
              FROM chat2work_employer e
              LEFT JOIN chat2work_listing l ON l.employer_id = e.id
             WHERE e.id IN %s
             GROUP BY e.id, e.name
             ORDER BY 2 DESC, e.name
            OFFSET %s LIMIT %s
        """, [tuple(ids), offset, limit])
        page = self.env.cr.fetchall()
        by_id = {e.id: e for e in Employer.browse([row[0] for row in page])}
        return [self._employer_row(by_id[employer_id], open_count) for employer_id, open_count in page]

    @api.model
    def ws_employer(self, employer_id):
        self._check_agent()
        employer = self.env['chat2work.employer'].browse(int(employer_id or 0)).exists()
        if not employer:
            return False
        listings = employer.with_context(active_test=False).listing_ids
        open_jobs = listings.filtered(lambda l: l.state == 'open')

        def host(url):
            netloc = urlparse(url if '://' in url else '//' + url).netloc.lower()
            return netloc[4:] if netloc.startswith('www.') else netloc

        links = {}
        for listing in listings:
            if listing.apply_url:
                site = host(listing.apply_url) or listing.apply_url
                links[site] = links.get(site, 0) + 1
        contacts = sorted({l.apply_contact.strip() for l in listings if (l.apply_contact or '').strip()})
        places = sorted({l.location.strip() for l in listings if (l.location or '').strip()})
        first = min(listings.mapped('first_seen_at'), default=False)
        matches = self.env['chat2work.listing.match'].search_count(
            [('listing_id', 'in', open_jobs.ids), ('state', '!=', 'rejected')]) if open_jobs else 0

        messages = self.env['mail.message'].sudo().search(
            [('model', '=', 'chat2work.employer'), ('res_id', '=', employer.id),
             ('message_type', '=', 'comment'), ('body', '!=', False)],
            order='id desc', limit=HISTORY_SHOWN)
        history = [{'id': m.id, 'at': _dt(m.date), 'who': m.author_id.name or '',
                    'text': html2plaintext(m.body or '').strip()} for m in messages]
        history = [h for h in history if h['text']]

        row = self._employer_row(employer)
        row.update({
            'names': [employer.name] + employer.alias_ids.mapped('name'),
            'first_seen': _dt(first) if first else False,
            'sources': listings.source_id.mapped('name'),
            'links': [{'site': site, 'jobs': n} for site, n in sorted(links.items(), key=lambda kv: -kv[1])[:4]],
            'contacts': contacts[:3],
            'places': places[:6],
            'stats': [employer.listing_count, len(open_jobs), matches,
                      len(listings.filtered(lambda l: l.verification_state == 'verified'))],
            'checks': [{'key': key, 'label': employer._fields[key].string, 'done': employer[key]} for key in CHECKS],
            'registration_no': employer.registration_no or '',
            'note': employer.note or '',
            'checked_by': employer.checked_by_id.name or '',
            'checked_at': _dt(employer.checked_at) if employer.checked_at else False,
            'jobs_list': [{
                'id': l.id, 'name': l.title, 'location': l.location or '',
                'closing_on': fields.Date.to_string(l.closing_on) if l.closing_on else False,
                'state': l.state, 'work_state': l.work_state, 'work_label': self._label(l, 'work_state'),
            } for l in listings.sorted(lambda l: (l.state != 'open', l.closing_on or fields.Date.today(), -l.id))[:JOBS_SHOWN]],
            'jobs_more': max(len(listings) - JOBS_SHOWN, 0),
            'similar': [{
                'id': other.id, 'name': other.name, 'jobs': other.listing_count, 'open': other.open_count,
                'state_label': self._label(other, 'state'),
            } for other in employer._similar()],
            'history': history,
        })
        return row

    @api.model
    def ws_employer_save(self, employer_id, values=None, state=None):
        """Keep the checklist and note, and the agent's answer when there is one."""
        self._check_agent()
        employer = self._employer(employer_id)
        values = values or {}
        vals = {key: bool(values[key]) for key in CHECKS if key in values}
        for key in ('registration_no', 'note'):
            if key in values:
                vals[key] = (values[key] or '').strip() or False
        if 'recruiter' in values:
            vals['is_recruiter'] = bool(values['recruiter'])
        if vals:
            employer.write(vals)
        if state:
            employer.action_set_state(state)
            note = (employer.note or '').strip()
            employer.message_post(body='%s%s' % (self._label(employer, 'state'), ': %s' % note if note else ''),
                                  message_type='comment', subtype_xmlid='mail.mt_note')
        return self.ws_employer(employer.id)

    @api.model
    def ws_employer_join(self, employer_id, other_id):
        self._check_agent()
        employer = self._employer(employer_id)
        employer.action_join(self._employer(other_id))
        return self.ws_employer(employer.id)

    @api.model
    def ws_employer_not_same(self, employer_id, other_id):
        self._check_agent()
        employer = self._employer(employer_id)
        employer.action_not_same(self._employer(other_id))
        return self.ws_employer(employer.id)

    # ── The flag on a job ────────────────────────────────────────────────────

    @api.model
    def ws_listing(self, listing_id):
        row = super().ws_listing(listing_id)
        if row:
            employer = self.env['chat2work.listing'].browse(listing_id).employer_id
            row['employer_check'] = {
                'id': employer.id, 'name': employer.name, 'state': employer.state,
                'state_label': self._label(employer, 'state'),
                'by': employer.checked_by_id.name or '',
                'at': _dt(employer.checked_at) if employer.checked_at else False,
            } if employer else False
        return row
