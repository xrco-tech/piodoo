# -*- coding: utf-8 -*-
"""Chat2Work USSD flow (spec v1.0, 16 Oct 2026).

A code-driven state machine rather than a whatsapp.chatbot step tree: the spec
needs conditional branching (recognised vs new caller), SA ID validation with a
3-strike lock, "Invalid choice" re-display with a 3-strike exit, and — for
POPIA — nothing stored about the caller before consent. The step engine can't
express those, and its inbound path creates a res.partner for every dialler.

Routing: a comm.ussd.account with flow_engine='chat2work' is dispatched here by
the /ussd/inbound controller override (controllers/ussd.py). Screen ids below
match the spec (S01A, S04-ERR1, ...).
"""

import base64
import hashlib
import hmac
import logging
import re
from datetime import date, timedelta

from odoo import api, fields, models, tools

_logger = logging.getLogger(__name__)

MAX_INVALID = 3
MAX_ID_ATTEMPTS = 3
NAME_MAX = 15
SCREEN_MAX = 160

EMPLOYMENT = {
    '1': 'unemployed',
    '2': 'employed',
    '3': 'self_employed',
    '4': 'student',
}

STATUS_MENU = (
    "What is your current employment status?\n"
    "1. Unemployed\n2. Employed\n3. Self-employed\n4. Student\n0. Back"
)
INTENT_MENU = "Are you looking for a new job?\n1. Yes\n2. No\n0. Back"


# ── SA ID + phone helpers ────────────────────────────────────────────────────

def parse_sa_id(value, today=None):
    """Return the date of birth for a valid 13-digit SA ID number, else None.

    Checks: 13 digits, real YYMMDD date, citizenship digit 0/1, Luhn checksum.
    The century is inferred: a 2-digit year that would put the birth date in
    the future belongs to the 1900s.
    """
    if not value or not re.fullmatch(r'\d{13}', value):
        return None
    if value[10] not in '01':
        return None
    total = 0
    for i, ch in enumerate(reversed(value)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    if total % 10:
        return None
    today = today or date.today()
    yy, mm, dd = int(value[0:2]), int(value[2:4]), int(value[4:6])
    for century in (2000, 1900):
        try:
            dob = date(century + yy, mm, dd)
        except ValueError:
            return None
        if dob <= today:
            return dob
    return None


def age_on(dob, today=None):
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def normalize_msisdn(raw):
    """'+27 82 123 4567' / '27821234567' / '0821234567' → '+27821234567'."""
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('0') and len(digits) == 10:
        digits = '27' + digits[1:]
    return '+' + digits if digits else ''


def msisdn_variants(e164):
    digits = e164.lstrip('+')
    variants = {e164, digits}
    if digits.startswith('27') and len(digits) == 11:
        variants.add('0' + digits[2:])
    return list(variants)


def display_msisdn(e164):
    """Show SA numbers in the local 0XX format callers recognise."""
    digits = e164.lstrip('+')
    if digits.startswith('27') and len(digits) == 11:
        return '0' + digits[2:]
    return e164


class Chat2workUssdSession(models.Model):
    _name = 'chat2work.ussd.session'
    _description = 'Chat2Work USSD Session'
    _order = 'create_date desc'
    _rec_name = 'session_id'

    session_id = fields.Char(required=True, index=True, readonly=True)
    msisdn = fields.Char('MSISDN', readonly=True)
    service_code = fields.Char(readonly=True)
    screen = fields.Char(readonly=True)
    candidate_id = fields.Many2one('chat2work.candidate', ondelete='set null', readonly=True)
    # Pending profile answers. The ID number is only ever held encrypted.
    data = fields.Json(default=lambda self: {}, readonly=True)
    invalid_count = fields.Integer(readonly=True)
    id_attempts = fields.Integer(readonly=True)
    last_response = fields.Text(readonly=True)

    _sql_constraints = [
        ('session_id_unique', 'UNIQUE(session_id)', 'Duplicate USSD session id.'),
    ]

    # ── Entry point ──────────────────────────────────────────────────────────

    @api.model
    def ussd_handle(self, session_id, service_code, phone_number, text, latest_input):
        """One gateway turn → 'CON …' / 'END …' response string."""
        self = self.sudo()
        try:
            session = self.search([('session_id', '=', session_id)], limit=1)
            if not session:
                if text:
                    # A continuing turn whose session we no longer hold
                    # (purged or expired) — the spec's SYS-TIMEOUT.
                    return 'END ' + self._t_timeout(service_code)
                session = self.create({
                    'session_id': session_id,
                    'service_code': service_code,
                    'msisdn': normalize_msisdn(phone_number),
                })
                body, end = session._start()
            else:
                body, end = session._advance((latest_input or '').strip())
            if len(body) > SCREEN_MAX:
                _logger.warning("chat2work USSD screen %s is %d chars (>%d)",
                                session.screen, len(body), SCREEN_MAX)
            if end:
                session.unlink()
            else:
                session.last_response = body
            return ('END ' if end else 'CON ') + body
        except Exception:
            _logger.exception("chat2work USSD error in session %s", session_id)
            return 'END Service unavailable. Please try again later.'

    @api.model
    def ussd_session_closed(self, session_id):
        self.sudo().search([('session_id', '=', session_id)]).unlink()

    @api.model
    def _gc_stale_sessions(self):
        """Gateways cap sessions at ~1-3 min; drop anything abandoned."""
        cutoff = fields.Datetime.now() - timedelta(minutes=15)
        self.sudo().search([('write_date', '<', cutoff)]).unlink()

    # ── Config ───────────────────────────────────────────────────────────────

    def _param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param('chat2work.' + key, default)

    def _age_range(self):
        return int(self._param('ussd_age_min', 18)), int(self._param('ussd_age_max', 34))

    def _code(self):
        return self.service_code or self._param('ussd_service_code', '')

    def _t_timeout(self, code):
        return "Session expired. Dial %s to start again." % code

    # ── State machine ────────────────────────────────────────────────────────

    def _start(self):
        try:
            self.candidate_id = self.env['chat2work.candidate'].search(
                [('phone', 'in', msisdn_variants(self.msisdn))], limit=1)
        except Exception:
            _logger.exception("chat2work USSD lookup failed; treating as new caller")
            self.candidate_id = False
        return self._goto('S01A' if self.candidate_id else 'S01B')

    def _advance(self, inp):
        result = getattr(self, '_on_' + self.screen.replace('-', '_'))(inp)
        if result is None:
            self.invalid_count += 1
            if self.invalid_count >= MAX_INVALID:
                return self._end_exit()
            return "Invalid choice. Please try again.\n" + self._render(self.screen), False
        self.invalid_count = 0
        return result

    def _goto(self, screen):
        self.screen = screen
        return self._render(screen), False

    def _render(self, screen):
        if screen == 'S01A':
            name = (self.candidate_id.name or '').strip()[:NAME_MAX].strip()
            greeting = ("Hi %s." % name) if name else "Welcome back to Chat2Work."
            return greeting + " What would you like to do?\n1. Update Status\n2. Request Callback\n0. Exit"
        if screen == 'S01B':
            return "Welcome to Chat2Work. What would you like to do?\n1. Create Profile\n2. Request Callback\n0. Exit"
        if screen == 'S02':
            return ("Chat2Work will store your details to help you find work. Terms: %s\n"
                    "1. I agree\n2. I do not agree") % self._param('ussd_terms_url', '')
        if screen == 'S03':
            return "Do you use %s on WhatsApp too?\n1. Yes\n2. No\n0. Back" % display_msisdn(self.msisdn)
        if screen == 'S04':
            return "Enter your 13-digit SA ID number:\n0. Back"
        if screen == 'S04-ERR1':
            return "Invalid ID number. Please check and try again.\n1. Try again\n0. Main Menu"
        if screen == 'S04-ERR2':
            return "This ID is already registered.\n1. Request Callback\n0. Exit"
        if screen in ('S05', 'S08'):
            return STATUS_MENU
        if screen in ('S06', 'S09'):
            return INTENT_MENU
        raise ValueError("Unknown USSD screen %s" % screen)

    def _set(self, **vals):
        self.data = dict(self.data or {}, **vals)

    # Welcome
    def _on_S01A(self, inp):
        return {'1': lambda: self._goto('S08'), '2': self._end_callback,
                '0': self._end_exit}.get(inp, lambda: None)()

    def _on_S01B(self, inp):
        return {'1': lambda: self._goto('S02'), '2': self._end_callback,
                '0': self._end_exit}.get(inp, lambda: None)()

    # Create profile
    def _on_S02(self, inp):
        if inp == '1':
            self._set(consent_at=fields.Datetime.to_string(fields.Datetime.now()))
            return self._goto('S03')
        if inp == '2':
            self.data = {}
            return "No problem. Nothing was saved. Dial %s any time to start again." % self._code(), True
        return None

    def _on_S03(self, inp):
        if inp in ('1', '2'):
            self._set(whatsapp=inp == '1')
            return self._goto('S04')
        if inp == '0':
            return self._goto('S02')
        return None

    def _on_S04(self, inp):
        if inp == '0':
            return self._goto('S03')
        Candidate = self.env['chat2work.candidate']
        dob = parse_sa_id(inp)
        if not dob:
            self.id_attempts += 1
            if self.id_attempts >= MAX_ID_ATTEMPTS:
                return ("Too many attempts. Please try again later or dial %s "
                        "and request a callback." % self._code()), True
            return self._goto('S04-ERR1')
        id_hash = Candidate._id_number_hash(inp)
        if Candidate.with_context(active_test=False).search_count([('id_number_hash', '=', id_hash)]):
            return self._goto('S04-ERR2')
        lo, hi = self._age_range()
        if not lo <= age_on(dob) <= hi:
            return "Sorry, Chat2Work is for ages %s-%s. Thank you for your interest." % (lo, hi), True
        self._set(id_hash=id_hash, id_enc=Candidate._id_number_encrypt(inp))
        return self._goto('S05')

    def _on_S04_ERR1(self, inp):
        if inp == '1':
            return self._goto('S04')
        if inp == '0':
            self.data = {}
            return self._goto('S01B')
        return None

    def _on_S04_ERR2(self, inp):
        if inp == '1':
            return self._end_callback()
        if inp == '0':
            return self._end_exit()
        return None

    def _on_S05(self, inp):
        if inp in EMPLOYMENT:
            self._set(employment=EMPLOYMENT[inp])
            return self._goto('S06')
        if inp == '0':
            return self._goto('S04')
        return None

    def _on_S06(self, inp):
        if inp in ('1', '2'):
            return self._create_profile(job_seeking=inp == '1')
        if inp == '0':
            return self._goto('S05')
        return None

    def _create_profile(self, job_seeking):
        d = self.data or {}
        partner = self.env['res.partner'].search(
            ['|', ('mobile', 'in', msisdn_variants(self.msisdn)),
             ('phone', 'in', msisdn_variants(self.msisdn))], limit=1)
        self.env['chat2work.candidate'].create({
            'name': partner.name if partner else False,
            'partner_id': partner.id or False,
            'phone': self.msisdn,
            'registered_via': 'ussd',
            'whatsapp_opt_in': bool(d.get('whatsapp')),
            'id_number_hash': d['id_hash'],
            'id_number_encrypted': d['id_enc'],
            'employment_status': d['employment'],
            'job_seeking': job_seeking,
            'consent_at': d['consent_at'],
            'status_updated_at': fields.Datetime.now(),
        })
        channel = "WhatsApp/SMS" if d.get('whatsapp') else "SMS"
        return "Profile created! We will contact you soon via %s." % channel, True

    # Update status (recognised callers)
    def _on_S08(self, inp):
        if inp in EMPLOYMENT:
            self._set(employment=EMPLOYMENT[inp])
            return self._goto('S09')
        if inp == '0':
            return self._goto('S01A')
        return None

    def _on_S09(self, inp):
        if inp in ('1', '2'):
            self.candidate_id.write({
                'employment_status': self.data['employment'],
                'job_seeking': inp == '1',
                'status_updated_at': fields.Datetime.now(),
            })
            return "Status updated. Thank you! We will be in touch soon.", True
        if inp == '0':
            return self._goto('S08')
        return None

    # Terminal screens
    def _end_callback(self):
        self.env['chat2work.callback.request'].request_callback(
            partner=self.candidate_id.partner_id or None, phone=self.msisdn, channel='ussd')
        return ("Callback requested for %s. A contact centre agent will call you shortly."
                % display_msisdn(self.msisdn)), True

    def _end_exit(self):
        return "Session ended. Dial %s to start again." % self._code(), True


class Chat2workCandidateIdentity(models.Model):
    """ID-number protection for candidate profiles (spec §8): the number is
    stored Fernet-encrypted, with an HMAC for duplicate checks, and is never
    shown on USSD screens."""
    _inherit = 'chat2work.candidate'

    @api.model
    def _id_secret(self):
        secret = tools.config.get('chat2work_id_key')
        if secret:
            return secret.encode()
        ICP = self.env['ir.config_parameter'].sudo()
        secret = ICP.get_param('chat2work.id_encryption_key')
        if not secret:
            from cryptography.fernet import Fernet
            secret = Fernet.generate_key().decode()
            ICP.set_param('chat2work.id_encryption_key', secret)
        return secret.encode()

    @api.model
    def _fernet(self):
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(b'enc:' + self._id_secret()).digest())
        return Fernet(key)

    @api.model
    def _id_number_hash(self, id_number):
        return hmac.new(b'hash:' + self._id_secret(), id_number.encode(), hashlib.sha256).hexdigest()

    @api.model
    def _id_number_encrypt(self, id_number):
        return self._fernet().encrypt(id_number.encode()).decode()

    def _id_number_decrypt(self):
        self.ensure_one()
        if not self.id_number_encrypted:
            return False
        return self._fernet().decrypt(self.id_number_encrypted.encode()).decode()
