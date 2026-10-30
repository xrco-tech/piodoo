# -*- coding: utf-8 -*-
"""Outside job listings and the candidates suggested for them.

A source is a manual import or a CSV feed. Rows are matched to existing
listings by the source's reference (or employer + title + location when there
is none), so re-importing updates a listing instead of duplicating it.
"""

import csv
import hashlib
import io
import logging
import re

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.chat2work.models.chat2work_pipeline import PROVINCES

_logger = logging.getLogger(__name__)

FEED_TIMEOUT = 30
FEED_MAX_BYTES = 10 * 1024 * 1024
SUGGESTIONS_PER_LISTING = 20
UNAVAILABLE_STAGES = ('placed', 'not_available')
KEYWORD_POINTS_MAX = 3
STOPWORDS = {
    'with', 'from', 'that', 'this', 'have', 'will', 'your', 'must', 'and', 'the', 'for', 'are',
    'work', 'working', 'experience', 'required', 'requirements', 'ability', 'skills', 'good',
    'years', 'year', 'minimum', 'position', 'role', 'looking', 'candidate', 'south', 'africa',
}
FIELDS = [
    ('call_centre', 'Call Centre'),
    ('retail', 'Retail'),
    ('warehouse', 'Warehouse / Driver'),
    ('admin', 'Admin / General'),
    ('other', 'Other'),
]
PROVINCE_ALIASES = {
    'kwazulu natal': 'kzn', 'gp': 'gauteng', 'wc': 'western_cape', 'ec': 'eastern_cape',
    'lp': 'limpopo', 'mp': 'mpumalanga', 'nw': 'north_west', 'fs': 'free_state', 'nc': 'northern_cape',
}
FIELD_ALIASES = {'warehouse': 'warehouse', 'driver': 'warehouse', 'admin': 'admin', 'general': 'admin'}
# What decides that a listing changed, and what a CSV row may set.
CONTENT_FIELDS = ('title', 'employer', 'location', 'province', 'field', 'employment_type', 'salary',
                  'description', 'requirements', 'apply_url', 'apply_contact', 'posted_on', 'closing_on')


def _key(value):
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


def _choice(value, choices, aliases):
    """The selection key for free text ("Western Cape", "WC"), else False."""
    key = _key(value)
    for code, label in choices:
        if key in (_key(code), _key(label)):
            return code
    return aliases.get(key, False)


def _keywords(text):
    return {w for w in re.findall(r'[a-z]{4,}', (text or '').lower())} - STOPWORDS


class Chat2workListingSource(models.Model):
    _name = 'chat2work.listing.source'
    _description = 'Chat2Work Job Listing Source'
    _order = 'name'

    name = fields.Char(required=True)
    kind = fields.Selection([('manual', 'Manual import'), ('csv_feed', 'CSV feed')],
                            default='manual', required=True)
    feed_url = fields.Char('Feed URL', help="HTTPS address of a CSV file, e.g. a published Google Sheet.")
    active = fields.Boolean(default=True)
    last_run_at = fields.Datetime(readonly=True)
    last_result = fields.Char(readonly=True)
    listing_count = fields.Integer('Listings', compute='_compute_listing_count')

    def _compute_listing_count(self):
        counts = dict(self.env['chat2work.listing'].with_context(active_test=False)._read_group(
            [('source_id', 'in', self.ids)], ['source_id'], ['__count']))
        for rec in self:
            rec.listing_count = counts.get(rec, 0)

    def _import_csv(self, content, close_missing=False):
        """Create or update this source's listings from CSV bytes. Returns a summary."""
        self.ensure_one()
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('latin-1')  # Excel's usual CSV encoding
        reader = csv.DictReader(io.StringIO(text))
        if 'title' not in [_key(h).replace(' ', '_') for h in reader.fieldnames or []]:
            raise UserError("The file needs a 'title' column.")
        Listing = self.env['chat2work.listing'].with_context(active_test=False)
        now = fields.Datetime.now()
        created = updated = unchanged = skipped = 0
        seen = Listing.browse()
        for row in reader:
            row = {_key(k).replace(' ', '_'): (v or '').strip() for k, v in row.items() if k}
            vals = Listing._vals_from_row(row)
            if vals is None:
                skipped += 1
                continue
            listing = Listing.search([('source_id', '=', self.id), ('external_ref', '=', vals['external_ref'])], limit=1)
            content_hash = Listing._content_hash(vals)
            if not listing:
                listing = Listing.create(dict(vals, source_id=self.id, content_hash=content_hash, first_seen_at=now,
                                              last_seen_at=now, content_updated_at=now))
                created += 1
            elif listing.content_hash != content_hash:
                listing.write(dict(vals, content_hash=content_hash, last_seen_at=now, content_updated_at=now,
                                   state='open'))
                updated += 1
            else:
                listing.write({'last_seen_at': now, 'state': 'open' if listing.state == 'closed' else listing.state})
                unchanged += 1
            seen |= listing
        closed = 0
        if close_missing:
            missing = Listing.search([('source_id', '=', self.id), ('state', '=', 'open'), ('id', 'not in', seen.ids)])
            missing.write({'state': 'closed'})
            closed = len(missing)
        Listing.search([('id', 'in', seen.ids)])._close_expired()
        summary = "%d new, %d updated, %d unchanged, %d closed, %d skipped (no title)" % (
            created, updated, unchanged, closed, skipped)
        self.write({'last_run_at': now, 'last_result': summary})
        return summary

    def _fetch_feed(self):
        self.ensure_one()
        if not (self.feed_url or '').startswith('https://'):
            raise UserError("The feed URL must start with https://")
        response = requests.get(self.feed_url, timeout=FEED_TIMEOUT, stream=True)
        response.raise_for_status()
        content = response.raw.read(FEED_MAX_BYTES + 1, decode_content=True)
        if len(content) > FEED_MAX_BYTES:
            raise UserError("The feed is bigger than 10 MB.")
        # A feed lists everything that's current, so what's gone from it has closed.
        return self._import_csv(content, close_missing=True)

    def action_fetch_now(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': self.name, 'message': self._fetch_feed(), 'sticky': False,
                       'next': {'type': 'ir.actions.act_window_close'}},
        }


class Chat2workListing(models.Model):
    _name = 'chat2work.listing'
    _description = 'Chat2Work Job Listing'
    _order = 'content_updated_at desc, id desc'
    _rec_name = 'title'

    source_id = fields.Many2one('chat2work.listing.source', required=True, ondelete='restrict', index=True,
                                default=lambda self: self.env.ref('chat2work_jobs.listing_source_manual', False))
    external_ref = fields.Char('Source Reference', index=True, copy=False,
                               help="The source's ID for this listing; used to spot updates.")
    title = fields.Char(required=True)
    employer = fields.Char()
    location = fields.Char('Town / Area')
    province = fields.Selection(PROVINCES, index=True)
    field = fields.Selection(FIELDS, 'Type of Work', index=True)
    employment_type = fields.Char()
    salary = fields.Char()
    description = fields.Text()
    requirements = fields.Text()
    apply_url = fields.Char('Apply Link')
    apply_contact = fields.Char('Apply Contact')
    posted_on = fields.Date()
    closing_on = fields.Date(index=True)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed')], default='open', required=True, index=True)
    active = fields.Boolean(default=True)
    content_hash = fields.Char(readonly=True, copy=False)
    first_seen_at = fields.Datetime(readonly=True, copy=False, default=fields.Datetime.now)
    last_seen_at = fields.Datetime(readonly=True, copy=False, default=fields.Datetime.now)
    content_updated_at = fields.Datetime('Last Changed', readonly=True, copy=False, default=fields.Datetime.now)
    match_ids = fields.One2many('chat2work.listing.match', 'listing_id', 'Candidates')
    suggested_count = fields.Integer('To Review', compute='_compute_suggested_count')

    _sql_constraints = [
        ('source_ref_unique', 'UNIQUE(source_id, external_ref)', 'This source already has a listing with this reference.'),
    ]

    @api.depends('match_ids.state')
    def _compute_suggested_count(self):
        for rec in self:
            rec.suggested_count = len(rec.match_ids.filtered(lambda m: m.state == 'suggested'))

    # ── Import ───────────────────────────────────────────────────────────────

    @api.model
    def _parse_date(self, value):
        try:
            return fields.Date.to_date(value) if value else False
        except ValueError:
            return False

    @api.model
    def _vals_from_row(self, row):
        """Listing values from a CSV row with normalised headers; None without a title."""
        title = row.get('title')
        if not title:
            return None
        vals = {
            'title': title[:200],
            'employer': row.get('employer', ''),
            'location': row.get('location', ''),
            'province': _choice(row.get('province'), PROVINCES, PROVINCE_ALIASES),
            'field': _choice(row.get('field'), FIELDS, FIELD_ALIASES),
            'employment_type': row.get('employment_type', ''),
            'salary': row.get('salary', ''),
            'description': row.get('description', ''),
            'requirements': row.get('requirements', ''),
            'apply_url': row.get('apply_url', ''),
            'apply_contact': row.get('apply_contact', ''),
            'posted_on': self._parse_date(row.get('posted_on')),
            'closing_on': self._parse_date(row.get('closing_on')),
        }
        vals['external_ref'] = row.get('external_ref') or hashlib.sha256(
            '|'.join(_key(vals[f]) for f in ('employer', 'title', 'location')).encode()).hexdigest()[:32]
        return vals

    @api.model
    def _content_hash(self, vals):
        return hashlib.sha256(repr([str(vals.get(f) or '') for f in CONTENT_FIELDS]).encode()).hexdigest()

    def _close_expired(self):
        today = fields.Date.context_today(self)
        self.filtered(lambda r: r.state == 'open' and r.closing_on and r.closing_on < today).write({'state': 'closed'})

    # ── Suggestions ──────────────────────────────────────────────────────────

    def _score_candidate(self, candidate):
        """(score, reasons) for a candidate, or None if they can't be suggested.

        A province or type of work that's known on both sides and differs rules
        the candidate out; unknown ones count for nothing either way.
        """
        self.ensure_one()
        for fname in ('province', 'field'):
            if self[fname] and candidate[fname] and self[fname] != candidate[fname]:
                return None
        score, reasons = 0, []
        if self.province and candidate.province == self.province:
            score += 2
            reasons.append('same province')
        if self.field and candidate.field == self.field:
            score += 2
            reasons.append('same type of work')
        if candidate.employment_status == 'unemployed':
            score += 1
            reasons.append('unemployed')
        if candidate.cv_text:
            overlap = _keywords(' '.join(filter(None, (self.title, self.requirements)))) & _keywords(candidate.cv_text)
            if overlap:
                score += min(len(overlap), KEYWORD_POINTS_MAX)
                reasons.append('CV mentions: %s' % ', '.join(sorted(overlap)[:5]))
        return score, reasons

    def action_suggest_candidates(self):
        """Add the best-scoring candidates not yet considered for each listing."""
        candidates = self.env['chat2work.candidate'].search([
            ('job_seeking', '=', True), ('stage', 'not in', UNAVAILABLE_STAGES),
        ])
        Match = self.env['chat2work.listing.match']
        for listing in self.filtered(lambda r: r.state == 'open'):
            considered = listing.match_ids.candidate_id
            scored = []
            for candidate in candidates - considered:
                result = listing._score_candidate(candidate)
                if result:
                    scored.append((result[0], candidate.id, result[1]))
            scored.sort(key=lambda s: (-s[0], s[1]))
            room = SUGGESTIONS_PER_LISTING - len(listing.match_ids.filtered(lambda m: m.state == 'suggested'))
            Match.create([{'listing_id': listing.id, 'candidate_id': cid, 'score': score,
                           'reason': '; '.join(reasons)} for score, cid, reasons in scored[:max(room, 0)]])
        return True

    @api.model
    def _cron_daily(self):
        Source = self.env['chat2work.listing.source']
        for source in Source.search([('kind', '=', 'csv_feed')]):
            try:
                with self.env.cr.savepoint():
                    _logger.info("chat2work_jobs: %s: %s", source.name, source._fetch_feed())
            except Exception as e:  # noqa: BLE001 - one bad feed mustn't stop the others
                _logger.warning("chat2work_jobs: feed %s failed: %s", source.name, e)
                source.write({'last_run_at': fields.Datetime.now(), 'last_result': 'Failed: %s' % str(e)[:200]})
        self.search([('state', '=', 'open')])._close_expired()
        self.search([('state', '=', 'open')]).action_suggest_candidates()


class Chat2workListingMatch(models.Model):
    _name = 'chat2work.listing.match'
    _description = 'Chat2Work Listing Candidate'
    _order = 'score desc, id'

    listing_id = fields.Many2one('chat2work.listing', required=True, ondelete='cascade', index=True)
    # Goes with the candidate when their data is erased.
    candidate_id = fields.Many2one('chat2work.candidate', required=True, ondelete='cascade', index=True)
    state = fields.Selection([
        ('suggested', 'To review'),
        ('approved', 'Good match'),
        ('rejected', 'Not a match'),
    ], default='suggested', required=True, index=True)
    score = fields.Integer(readonly=True)
    reason = fields.Char('Why', readonly=True)
    note = fields.Char()
    candidate_phone = fields.Char(related='candidate_id.phone')
    candidate_status = fields.Selection(related='candidate_id.employment_status', string='Status')
    candidate_cv_state = fields.Selection(related='candidate_id.cv_state', string='CV')
    listing_state = fields.Selection(related='listing_id.state', string='Listing Status')

    _sql_constraints = [
        ('listing_candidate_unique', 'UNIQUE(listing_id, candidate_id)', 'This candidate is already on this listing.'),
    ]

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})


class Chat2workCandidateMatches(models.Model):
    _inherit = 'chat2work.candidate'

    listing_match_ids = fields.One2many('chat2work.listing.match', 'candidate_id', 'Job Matches')
