# -*- coding: utf-8 -*-
"""Occupations and education levels for matching candidates to job listings.

Occupations are the ILO's ISCO-08 groups. South Africa's OFO 2021 is built on
them: an OFO code's first four digits (2021-4222xx) are the ISCO unit group,
so a listing coded here lines up with OFO. Matching works at unit-group level
(4 digits), with the minor (3) and sub-major (2) groups as "related work".

A listing gets its occupation from the import (an ofo_code column), from its
title when that matches an ISCO name or example title, or from Claude, which
picks one from this list. Agents can change it; theirs is kept.

The five types of work candidates choose at sign-up stand for a few unit
groups each (WORK_GROUPS).
"""

import json
import logging
import re

import requests

from odoo import api, fields, models

from odoo.addons.chat2work.models.chat2work_cv import _commit

from .chat2work_listing import _key

_logger = logging.getLogger(__name__)

# National Qualifications Framework levels: what a candidate has, or what a job asks for.
NQF_LEVELS = [
    ('3', 'Below matric'),
    ('4', 'Matric (NQF 4)'),
    ('5', 'Higher certificate (NQF 5)'),
    ('6', 'Diploma (NQF 6)'),
    ('7', 'Degree (NQF 7)'),
    ('8', 'Honours (NQF 8)'),
    ('9', "Master's (NQF 9)"),
    ('10', 'Doctorate (NQF 10)'),
]
NQF_ALIASES = {
    'below matric': '3', 'grade 9': '3', 'grade 10': '3', 'grade 11': '3', 'matric': '4', 'grade 12': '4',
    'nsc': '4', 'n4': '5', 'higher certificate': '5', 'certificate': '5', 'n6': '6', 'diploma': '6',
    'national diploma': '6', 'degree': '7', 'bachelor': '7', 'bachelors': '7', 'btech': '7', 'honours': '8',
    'postgraduate diploma': '8', 'masters': '9', 'master': '9', 'doctorate': '10', 'phd': '10',
}
# The sign-up choices and the ISCO-08 unit groups each stands for.
WORK_GROUPS = {
    'call_centre': ('4222', '4223', '4225', '4229', '5244'),
    'retail': ('5221', '5222', '5223', '5230', '5242', '5243', '5246', '5249', '9334'),
    'warehouse': ('4321', '4323', '8321', '8322', '8332', '8344', '9321', '9329', '9333'),
    'admin': ('3343', '4110', '4120', '4131', '4132', '4226', '4311', '4312', '4313', '4415', '4416', '4419'),
}
SOURCES = [('import', 'From the import'), ('title', 'From the title'), ('ai', 'Suggested by AI'),
           ('agent', 'Set by an agent')]
# Words in titles that say nothing about the occupation.
TITLE_NOISE = re.compile(
    r'\b(senior|snr|junior|jnr|trainee|assistant to|intern(ship)?|learnership|apprentice(ship)?|graduate|'
    r'programme|program|permanent|temporary|temp|contract|part[- ]time|full[- ]time|seasonal|x\s?\d+|\d+)\b')

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
DEFAULT_MODEL = 'claude-haiku-5-5'
REQUEST_TIMEOUT = 60
AI_BATCH = 40
DESCRIPTION_CHARS = 800
SYSTEM = """You code South African job listings to an ISCO-08 unit group (4 digits). The codes are listed below.
Pick the unit group for the job the listing hires for. Learnerships, internships and graduate programmes:
code the work the person will do; if it isn't clear what that is, answer "none". Answer "none" too when
nothing in the list fits.

%s"""


def _norm(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]+', ' ', (text or '').lower())).strip()


def clean_title(title):
    """The occupation part of a listing title: "Cashier - West Street, Durban" → "cashier"."""
    head = re.split(r'\s[-–|]\s|[:(/]', title or '')[0]
    return _norm(TITLE_NOISE.sub(' ', head.lower()))


def nqf_from_text(value):
    """An NQF_LEVELS key from "Matric", "NQF 6", "7"…, else False."""
    text = re.sub(r'[^a-z0-9 ]+', ' ', (value or '').lower()).split()
    text = ' '.join(text)
    found = re.fullmatch(r'(?:nqf\s*(?:level\s*)?)?(10|[3-9])', text)
    if found:
        return found.group(1)
    for alias in sorted(NQF_ALIASES, key=len, reverse=True):
        if re.search(r'\b%s\b' % alias, text):
            return NQF_ALIASES[alias]
    return False


def _singular(word):
    if word.endswith('ies'):
        return word[:-3] + 'y'
    if word.endswith(('sses', 'ches', 'shes')):
        return word[:-2]
    return word[:-1] if word.endswith('s') and not word.endswith('ss') else word


class Chat2workOccupation(models.Model):
    _name = 'chat2work.occupation'
    _description = 'Chat2Work Occupation (ISCO-08 / OFO)'
    _order = 'code'
    _parent_store = True
    _rec_names_search = ['code', 'name']

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    level = fields.Integer(required=True, help="1 major group, 2 sub-major, 3 minor, 4 unit group.")
    parent_id = fields.Many2one('chat2work.occupation', index=True, ondelete='restrict')
    parent_path = fields.Char(index=True)
    examples = fields.Text(help="Job titles classified here, one per line (from ISCO-08).")

    _sql_constraints = [('code_unique', 'UNIQUE(code)', 'This occupation code already exists.')]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s %s' % (rec.code, rec.name)

    @api.model
    def _c2w_from_code(self, value):
        """The unit group for "4222", "2021-422201" or "422201", else an empty recordset."""
        digits = re.sub(r'\D', '', re.sub(r'^\s*20\d\d-', '', value or ''))
        if len(digits) < 4:
            return self.browse()
        return self.search([('code', '=', digits[:4]), ('level', '=', 4)], limit=1)

    @api.model
    def _c2w_title_index(self):
        """{normalised title: unit group id} from the names and example titles."""
        index = {}
        for occ in self.search_read([('level', '=', 4)], ['name', 'examples']):
            titles = [occ['name']] + (occ['examples'] or '').splitlines()
            for title in titles:
                parts = re.split(r'\s+(?:and|or)\s+|,', title)
                for i, part in enumerate(parts):
                    words = _norm(re.sub(r'\(.*?\)', '', part)).split()
                    # A lone word is only a job when it's the plural noun that starts the
                    # name ("Cashiers and Ticket Clerks"), not a qualifier ("Production
                    # and…", "Driver (rickshaw)") or the tail of a shared noun ("…and Clerks").
                    if len(words) == 1 and (len(parts) > 1 and (i or not part.strip().endswith('s'))
                                            or '(' in part):
                        continue
                    key = ' '.join(_singular(w) for w in words)
                    if len(key) > 3:
                        index.setdefault(key, occ['id'])
        return index

    @api.model
    def _c2w_by_title(self, title, index=None):
        """The unit group whose name or example is this title, else an empty recordset."""
        index = index if index is not None else self._c2w_title_index()
        key = ' '.join(_singular(w) for w in clean_title(title).split())
        return self.browse(index[key]) if key in index else self.browse()

    def _c2w_unit_groups_text(self):
        units = self.search([('level', '=', 4)])
        return '\n'.join('%s %s' % (u.code, u.name) for u in units)


class Chat2workListingOccupation(models.Model):
    _inherit = 'chat2work.listing'

    occupation_id = fields.Many2one('chat2work.occupation', 'Occupation', index=True, tracking=True,
                                    domain=[('level', '=', 4)],
                                    help="ISCO-08 unit group, the first four digits of the OFO code.")
    occupation_source = fields.Selection(SOURCES, 'Occupation From', readonly=True, copy=False)
    occupation_checked_at = fields.Datetime(readonly=True, copy=False,
                                            help="When the AI last looked for an occupation, so it isn't asked again.")
    nqf_min = fields.Selection(NQF_LEVELS, 'Minimum Education', tracking=True)
    nqf_required = fields.Boolean('Education Required', tracking=True,
                                  help="Leave out candidates below the minimum. Otherwise they only score lower.")

    @api.model
    def _vals_from_row(self, row):
        """Also ofo_code (OFO or ISCO, e.g. 2021-422201 or 4222), nqf_min and education_required."""
        vals = super()._vals_from_row(row)
        if vals is None:
            return vals
        occupation = self.env['chat2work.occupation']._c2w_from_code(row.get('ofo_code') or row.get('isco_code'))
        if occupation:
            vals.update(occupation_id=occupation.id, occupation_source='import')
        nqf = nqf_from_text(row.get('nqf_min') or row.get('education'))
        if nqf:
            vals['nqf_min'] = nqf
        if row.get('education_required'):
            vals['nqf_required'] = _key(row['education_required']) in ('yes', 'y', 'true', '1', 'required')
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('occupation_id') and not vals.get('occupation_source'):
                vals['occupation_source'] = 'agent'
        records = super().create(vals_list)
        records.filtered(lambda r: not r.occupation_id)._c2w_code_by_title()
        records._c2w_fill_field()
        return records

    def write(self, vals):
        if 'occupation_id' in vals and 'occupation_source' not in vals:
            vals = dict(vals, occupation_source='agent' if vals['occupation_id'] else False)
        res = super().write(vals)
        if vals.get('occupation_id'):
            self._c2w_fill_field()
        return res

    def _c2w_fill_field(self):
        """Set the broad type of work from the occupation when it's still empty."""
        for rec in self.filtered(lambda r: r.occupation_id and not r.field):
            field = next((f for f, codes in WORK_GROUPS.items() if rec.occupation_id.code in codes), False)
            if field:
                rec.field = field

    def _c2w_code_by_title(self):
        Occupation = self.env['chat2work.occupation']
        index = Occupation._c2w_title_index()
        for rec in self:
            occupation = Occupation._c2w_by_title(rec.title, index)
            if occupation:
                rec.write({'occupation_id': occupation.id, 'occupation_source': 'title'})

    def action_suggest_occupation(self):
        """Title first, then the AI. Agents use it when the occupation is empty or looks wrong."""
        self._c2w_code_by_title()
        rest = self.filtered(lambda r: r.occupation_source != 'title')
        rest.write({'occupation_checked_at': False})
        rest._c2w_code_by_ai()

    def _c2w_code_by_ai(self):
        api_key = (self.env['ir.config_parameter'].sudo().get_param('comm_chatbot.anthropic_api_key') or '').strip()
        if not api_key:
            _logger.info("chat2work_jobs: no AI key, so listings are coded by title only")
            return
        Occupation = self.env['chat2work.occupation']
        system = SYSTEM % Occupation._c2w_unit_groups_text()
        for rec in self:
            try:
                code = rec._c2w_ai_occupation(api_key, system)
            except Exception as e:  # noqa: BLE001 - one listing mustn't stop the rest
                _logger.warning("chat2work_jobs: occupation for listing %s failed: %s", rec.id, e)
                continue
            occupation = Occupation._c2w_from_code(code) if code and code != 'none' else Occupation
            vals = {'occupation_checked_at': fields.Datetime.now()}
            if occupation and not rec.occupation_id:
                vals.update(occupation_id=occupation.id, occupation_source='ai')
            rec.write(vals)
            _commit(self.env)

    def _c2w_ai_occupation(self, api_key, system):
        """The unit group code Claude picks for this listing, or "none". Raises when it can't answer."""
        self.ensure_one()
        model = self.env['ir.config_parameter'].sudo().get_param('chat2work.occupation_model', DEFAULT_MODEL)
        listing = 'Title: %s\nEmployer: %s\n\n%s' % (
            self.title, self.employer or '-', ((self.description or '') + '\n' + (self.requirements or ''))[:DESCRIPTION_CHARS])
        response = requests.post(API_URL, timeout=REQUEST_TIMEOUT, headers={
            'x-api-key': api_key,
            'anthropic-version': API_VERSION,
            'content-type': 'application/json',
        }, json={
            'model': model,
            'max_tokens': 2000,
            'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
            'output_config': {'effort': 'low', 'format': {'type': 'json_schema', 'schema': {
                'type': 'object', 'additionalProperties': False, 'required': ['code'],
                'properties': {'code': {'type': 'string', 'description': '4-digit unit group code, or "none"'}},
            }}},
            'messages': [{'role': 'user', 'content': '<listing>\n%s\n</listing>' % listing.replace('</listing>', '')}],
        })
        if response.status_code != 200:
            raise ValueError('Anthropic returned %s' % response.status_code)
        body = response.json()
        if body.get('stop_reason') != 'end_turn':
            raise ValueError('Stopped early: %s' % body.get('stop_reason'))
        text = ''.join(b.get('text', '') for b in body.get('content', []) if b.get('type') == 'text')
        return (json.loads(text).get('code') or '').strip().lower()

    @api.model
    def _cron_code_occupations(self):
        """Ask the AI about open listings with no occupation, a batch at a time."""
        self.search([('state', '=', 'open'), ('occupation_id', '=', False), ('occupation_checked_at', '=', False)],
                    limit=AI_BATCH)._c2w_code_by_ai()


class Chat2workCandidateEducation(models.Model):
    _inherit = 'chat2work.candidate'

    nqf_level = fields.Selection(NQF_LEVELS, 'Highest Education', tracking=True)

    def _c2w_unit_groups(self):
        """ISCO unit group codes this candidate is looking for: from their type of work for now."""
        self.ensure_one()
        return set(WORK_GROUPS.get(self.field) or ())
