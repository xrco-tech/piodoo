# -*- coding: utf-8 -*-
"""Employers, so an agent checks each one once instead of on every job.

A listing only carries the employer's name as the job site typed it. Each
distinct name becomes an employer record; spellings an agent has joined are
kept as other names of the same employer, so later jobs land in one place.

An unchecked employer never blocks its jobs: they only carry a flag."""

import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [
    ('new', 'New, not checked'),
    ('unsure', "Can't tell yet"),
    ('verified', 'Verified'),
    ('invalid', 'Not genuine'),
]
CHECKS = ('check_registered', 'check_domain', 'check_confirmed', 'check_no_fees')
# Company-form words that do not tell two employers apart.
FORM_WORDS = {'pty', 'ltd', 'limited', 'proprietary', 'cc', 'inc', 'incorporated', 'npc', 'soc', 'rf', 'co'}
# Words dropped only when looking for possible duplicates to put to an agent.
LOOSE_WORDS = FORM_WORDS | {'the', 'group', 'grp', 'holdings', 'holding', 'sa', 'south', 'africa', 'company'}


def _words(name):
    return re.findall(r'[a-z0-9]+', (name or '').lower().replace('&', ' and '))


def name_key(name):
    """What two spellings must share to be the same employer without asking."""
    return ' '.join(w for w in _words(name) if w not in FORM_WORDS)


def loose_key(name):
    """A wider match, only ever used to suggest a possible duplicate."""
    return ''.join(w for w in _words(name) if w not in LOOSE_WORDS)


class Chat2workEmployer(models.Model):
    _name = 'chat2work.employer'
    _description = 'Chat2Work Employer'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    key = fields.Char(index=True, readonly=True, copy=False)
    loose = fields.Char(index=True, readonly=True, copy=False)
    alias_ids = fields.One2many('chat2work.employer.alias', 'employer_id', 'Other Spellings')
    state = fields.Selection(STATES, 'Check', default='new', required=True, index=True, tracking=True)
    is_recruiter = fields.Boolean('Recruits for Other Firms', tracking=True,
                                  help="An agency advertising jobs at other companies.")
    check_registered = fields.Boolean('The company is registered')
    check_domain = fields.Boolean('The website and email are theirs')
    check_confirmed = fields.Boolean('Someone there confirmed the jobs')
    check_no_fees = fields.Boolean('Applicants are never asked to pay')
    registration_no = fields.Char('Registration Number')
    note = fields.Text('How It Was Checked')
    checked_by_id = fields.Many2one('res.users', 'Checked By', readonly=True, copy=False)
    checked_at = fields.Datetime('Checked On', readonly=True, copy=False)
    listing_ids = fields.One2many('chat2work.listing', 'employer_id', 'Jobs')
    listing_count = fields.Integer('Jobs', compute='_compute_counts')
    open_count = fields.Integer('Open Jobs', compute='_compute_counts')
    distinct_ids = fields.Many2many(
        'chat2work.employer', 'chat2work_employer_distinct_rel', 'employer_id', 'other_id',
        string='Not the Same As', help="Employers an agent said are different, so they are not suggested again.")

    _sql_constraints = [('key_unique', 'unique(key)', 'This employer already exists.')]

    @api.depends('listing_ids.state')
    def _compute_counts(self):
        Listing = self.env['chat2work.listing']
        totals = dict(Listing._read_group([('employer_id', 'in', self.ids)], ['employer_id'], ['__count']))
        opens = dict(Listing._read_group(
            [('employer_id', 'in', self.ids), ('state', '=', 'open')], ['employer_id'], ['__count']))
        for employer in self:
            employer.listing_count = totals.get(employer, 0)
            employer.open_count = opens.get(employer, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['key'] = name_key(vals.get('name'))
            vals['loose'] = loose_key(vals.get('name'))
        return super().create(vals_list)

    def write(self, vals):
        if 'name' in vals:
            vals = dict(vals, key=name_key(vals['name']), loose=loose_key(vals['name']))
        return super().write(vals)

    # ── Finding the employer behind a name ───────────────────────────────────

    @api.model
    def _for_name(self, name):
        """The employer a job site's spelling belongs to, made on first sight.
        Empty for a listing that names no employer."""
        key = name_key(name)
        if not key:
            return self.browse()
        employer = self.search([('key', '=', key)], limit=1)
        if not employer:
            employer = self.env['chat2work.employer.alias'].search([('key', '=', key)], limit=1).employer_id
        return employer or self.create({'name': ' '.join((name or '').split())})

    def _similar(self):
        """Employers that may be this one under another spelling."""
        self.ensure_one()
        if len(self.loose) < 4:
            return self.browse()
        domain = [('id', '!=', self.id), ('id', 'not in', self.distinct_ids.ids),
                  '|', ('loose', '=', self.loose), ('loose', '=like', self.loose + '%')]
        found = self.search(domain, limit=5)
        if len(found) < 5:
            # ...or this one is the longer spelling of a shorter name.
            shorter = self.search([('id', '!=', self.id), ('id', 'not in', (found | self.distinct_ids).ids),
                                   ('loose', '!=', False)], limit=2000).filtered(
                lambda e: len(e.loose) >= 4 and self.loose.startswith(e.loose))
            found |= shorter[:5 - len(found)]
        return found

    # ── What an agent decides ────────────────────────────────────────────────

    def action_set_state(self, state):
        if state not in dict(STATES):
            raise UserError(_("Unknown answer."))
        for employer in self:
            employer.write({'state': state, 'checked_by_id': self.env.user.id, 'checked_at': fields.Datetime.now()})
        return True

    def action_join(self, other):
        """`other` is the same employer under another spelling: its jobs and
        spellings move here and it is removed."""
        self.ensure_one()
        other = other.exists()
        if not other or other == self:
            raise UserError(_("Pick another employer to join with this one."))
        Alias = self.env['chat2work.employer.alias']
        other.listing_ids.write({'employer_id': self.id})
        other.alias_ids.write({'employer_id': self.id})
        if other.key != self.key and not Alias.search_count([('key', '=', other.key)]):
            other_name, other_key = other.name, other.key
            other.unlink()
            Alias.create({'employer_id': self.id, 'name': other_name, 'key': other_key})
        else:
            other.unlink()
        self.message_post(body=_("Joined with another spelling of the same employer."),
                          message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def action_not_same(self, other):
        self.ensure_one()
        other = other.exists()
        if other and other != self:
            self.distinct_ids = [(4, other.id)]
            other.distinct_ids = [(4, self.id)]
        return True


class Chat2workEmployerAlias(models.Model):
    _name = 'chat2work.employer.alias'
    _description = 'Chat2Work Employer: Other Spelling'
    _order = 'name'

    employer_id = fields.Many2one('chat2work.employer', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True)
    key = fields.Char(required=True, index=True)

    _sql_constraints = [('key_unique', 'unique(key)', 'This spelling already belongs to an employer.')]


class Chat2workListingEmployer(models.Model):
    _inherit = 'chat2work.listing'

    employer_id = fields.Many2one('chat2work.employer', 'Employer Record', index=True, ondelete='set null',
                                  readonly=True, copy=False)
    employer_state = fields.Selection(related='employer_id.state', string='Employer Check')

    @api.model_create_multi
    def create(self, vals_list):
        listings = super().create(vals_list)
        listings._c2w_link_employer()
        return listings

    def write(self, vals):
        res = super().write(vals)
        if 'employer' in vals:
            self._c2w_link_employer()
        return res

    def _c2w_link_employer(self):
        """Point each listing at the employer its typed name belongs to."""
        Employer = self.env['chat2work.employer'].sudo()
        by_name = {}
        for listing in self.sudo():
            name = listing.employer or ''
            if name not in by_name:
                by_name[name] = Employer._for_name(name)
            if listing.employer_id != by_name[name]:
                listing.employer_id = by_name[name].id or False

    @api.model
    def _c2w_link_all_employers(self):
        """For listings that came in before employers existed."""
        self.with_context(active_test=False).search([('employer_id', '=', False)])._c2w_link_employer()
