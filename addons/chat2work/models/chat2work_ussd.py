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

STATUS_PROMPT = "What is your current employment status?"
STATUS_OPTIONS = [('1', 'Unemployed'), ('2', 'Employed'), ('3', 'Self-employed'),
                  ('4', 'Student'), ('0', 'Back')]
INTENT_PROMPT = "Are you looking for a new job?"
INTENT_OPTIONS = [('1', 'Yes'), ('2', 'No'), ('0', 'Back')]
# Short labels: with the "Invalid choice" line these screens must fit a USSD page.
PROVINCE_PROMPT = "Your province?"
PROVINCE_OPTIONS = [('1', 'Gauteng'), ('2', 'KZN'), ('3', 'W Cape'), ('4', 'E Cape'), ('5', 'Limpopo'),
                    ('6', 'Mpumalanga'), ('7', 'N West'), ('8', 'Free State'), ('9', 'N Cape'), ('0', 'Skip')]
PROVINCE_KEYS = {'1': 'gauteng', '2': 'kzn', '3': 'western_cape', '4': 'eastern_cape', '5': 'limpopo',
                 '6': 'mpumalanga', '7': 'north_west', '8': 'free_state', '9': 'northern_cape'}
FIELD_PROMPT = "What work do you want?"
FIELD_OPTIONS = [('1', 'Call centre'), ('2', 'Retail'), ('3', 'Warehouse/Driver'),
                 ('4', 'Admin'), ('5', 'Other'), ('0', 'Skip')]
FIELD_KEYS = {'1': 'call_centre', '2': 'retail', '3': 'warehouse', '4': 'admin', '5': 'other'}

# Question names for the activity log, so "Yes" reads as "WhatsApp: Yes".
SCREEN_TOPICS = {
    'S02': 'Terms', 'S03': 'WhatsApp', 'S05': 'Status', 'S08': 'Status',
    'S06': 'Looking for work', 'S09': 'Looking for work',
    'S10': 'Province', 'S11': 'Type of work',
}
# 13 digits, alone or grouped with spaces/dashes/dots ("930829 0197 084").
ID_LIKE = re.compile(r'(?<!\d)\d(?:[\s.-]?\d){12}(?!\d)')
ID_REDACTED = '[ID number]'


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


class Chat2workFlow(models.AbstractModel):
    """The Chat2Work conversation, shared by USSD and WhatsApp.

    Each channel's session model inherits this and supplies how a screen is
    shown (numbered USSD text, or WhatsApp buttons and lists) and how the
    caller is told to start again. Screens are defined once in _screen() as a
    prompt plus (key, label) options, so the two channels can't drift apart.
    """
    _name = 'chat2work.flow'
    _description = 'Chat2Work conversation flow'

    _channel = 'ussd'

    msisdn = fields.Char('MSISDN', readonly=True)
    screen = fields.Char(readonly=True)
    candidate_id = fields.Many2one('chat2work.candidate', ondelete='set null', readonly=True)
    # Pending profile answers. The ID number is only ever held encrypted.
    data = fields.Json(default=lambda self: {}, readonly=True)
    invalid_count = fields.Integer(readonly=True)
    id_attempts = fields.Integer(readonly=True)
    # Messages in and out, for the candidate's activity log. ID numbers are
    # never written here.
    transcript = fields.Json(default=lambda self: [], readonly=True)

    # ── Config ───────────────────────────────────────────────────────────────

    def _param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param('chat2work.' + key, default)

    def _age_range(self):
        return int(self._param('ussd_age_min', 18)), int(self._param('ussd_age_max', 34))

    def _restart_phrase(self):
        """How this channel starts a new session, e.g. 'dial *134*433*48#'."""
        raise NotImplementedError

    def _restart(self, capital=True):
        phrase = self._restart_phrase()
        return phrase[:1].upper() + phrase[1:] if capital else phrase

    # ── State machine ────────────────────────────────────────────────────────

    def _start(self):
        try:
            self.candidate_id = self.env['chat2work.candidate'].search(
                [('phone', 'in', msisdn_variants(self.msisdn))], limit=1)
        except Exception:
            _logger.exception("chat2work lookup failed; treating as new caller")
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
        """The screen as USSD text: prompt, then one numbered line per option."""
        prompt, options = self._screen(screen)
        return prompt + ''.join('\n%s. %s' % opt for opt in options)

    def _screen(self, screen):
        """(prompt, [(key, label), ...]) for a screen."""
        if screen == 'S01A':
            name = (self.candidate_id.name or '').strip()[:NAME_MAX].strip()
            greeting = ("Hi %s." % name) if name else "Welcome back to Chat2Work."
            return (greeting + " What would you like to do?",
                    [('1', 'Update Status'), ('2', 'Request Callback'), ('0', 'Exit')])
        if screen == 'S01B':
            return ("Welcome to Chat2Work. What would you like to do?",
                    [('1', 'Create Profile'), ('2', 'Request Callback'), ('0', 'Exit')])
        if screen == 'S02':
            return ("Chat2Work will store your details to help you find work. Terms: %s"
                    % self._param('ussd_terms_url', ''),
                    [('1', 'I agree'), ('2', 'I do not agree')])
        if screen == 'S03':
            return ("Do you use %s on WhatsApp too?" % display_msisdn(self.msisdn),
                    [('1', 'Yes'), ('2', 'No'), ('0', 'Back')])
        if screen == 'S04':
            return "Enter your 13-digit SA ID number:", [('0', 'Back')]
        if screen == 'S04-ERR1':
            return ("Invalid ID number. Please check and try again.",
                    [('1', 'Try again'), ('0', 'Main Menu')])
        if screen == 'S04-ERR2':
            return "This ID is already registered.", [('1', 'Request Callback'), ('0', 'Exit')]
        if screen in ('S05', 'S08'):
            return STATUS_PROMPT, STATUS_OPTIONS
        if screen in ('S06', 'S09'):
            return INTENT_PROMPT, INTENT_OPTIONS
        if screen == 'S10':
            return PROVINCE_PROMPT, PROVINCE_OPTIONS
        if screen == 'S11':
            return FIELD_PROMPT, FIELD_OPTIONS
        raise ValueError("Unknown Chat2Work screen %s" % screen)

    def _set(self, **vals):
        self.data = dict(self.data or {}, **vals)

    # ── Activity log ─────────────────────────────────────────────────────────

    def _note(self, direction, text, wa_message_id=None):
        entry = {'at': fields.Datetime.to_string(fields.Datetime.now()), 'dir': direction,
                 'text': ID_LIKE.sub(ID_REDACTED, text or '')}
        if wa_message_id:
            entry['wa'] = wa_message_id
        self.transcript = list(self.transcript or []) + [entry]

    def _note_input(self, inp):
        """Record a reply as what it means ("WhatsApp: Yes"), never an ID number."""
        if (self.screen == 'S04' and inp != '0') or ID_LIKE.fullmatch(inp or ''):
            text = ID_REDACTED
        else:
            _prompt, options = self._screen(self.screen)
            text = dict(options).get(inp, inp)
            topic = SCREEN_TOPICS.get(self.screen)
            if topic and inp in dict(options) and inp != '0':
                text = '%s: %s' % (topic, text)
        self._note('inbound', text)

    def _log_transcript(self):
        """Hand the session to the candidate's activity log. Only sessions tied
        to a profile are logged, so a caller who never consents leaves nothing."""
        if self.env.context.get('chat2work_ussd_simulation'):
            return
        for session in self:
            if not session.transcript:
                continue
            candidate = (self.env['chat2work.candidate'].browse((session.data or {}).get('created_candidate_id')).exists()
                         or session.candidate_id)
            if candidate:
                candidate._c2w_touch()
                candidate._c2w_log_session(session._channel, session.transcript)

    def unlink(self):
        self._log_transcript()
        return super().unlink()

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
            return self._after_consent()
        if inp == '2':
            self.data = {}
            return "No problem. Nothing was saved. %s any time to start again." % self._restart(), True
        return None

    def _after_consent(self):
        return self._goto('S03')

    def _on_S03(self, inp):
        if inp in ('1', '2'):
            self._set(whatsapp=inp == '1')
            return self._goto('S04')
        if inp == '0':
            return self._goto('S02')
        return None

    def _back_from_id(self):
        return self._goto('S03')

    def _on_S04(self, inp):
        if inp == '0':
            return self._back_from_id()
        Candidate = self.env['chat2work.candidate']
        dob = parse_sa_id(inp)
        if not dob:
            self.id_attempts += 1
            if self.id_attempts >= MAX_ID_ATTEMPTS:
                return ("Too many attempts. Please try again later or %s "
                        "and request a callback." % self._restart(capital=False)), True
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
        if re.fullmatch(r'\d{13}', inp or ''):
            # They typed the ID again instead of choosing "Try again".
            return self._on_S04(inp)
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
        if inp == '2':
            return self._create_profile(job_seeking=False)
        if inp == '1':
            # Save the profile now, so leaving at the questions below loses nothing.
            self._create_profile(job_seeking=True)
            self.candidate_id = self.data['created_candidate_id']
            return self._ask_preferences()
        if inp == '0':
            return self._goto('S05')
        return None

    # What they're looking for: used to match them to job listings. Optional.
    def _ask_preferences(self):
        if not self.candidate_id.province:
            return self._goto('S10')
        if not self.candidate_id.field:
            return self._goto('S11')
        return self._end_preferences()

    def _on_S10(self, inp):
        if inp in PROVINCE_KEYS:
            self.candidate_id.province = PROVINCE_KEYS[inp]
        elif inp != '0':
            return None
        return self._end_preferences() if self.candidate_id.field else self._goto('S11')

    def _on_S11(self, inp):
        if inp in FIELD_KEYS:
            self.candidate_id.field = FIELD_KEYS[inp]
        elif inp != '0':
            return None
        return self._end_preferences()

    def _end_preferences(self):
        if (self.data or {}).get('created_candidate_id'):
            return self._profile_created_text(self.candidate_id), True
        return "Status updated. Thank you! We will be in touch soon.", True

    def _candidate_extra_vals(self):
        return {}

    def _create_profile(self, job_seeking):
        d = self.data or {}
        partner = self.env['res.partner'].search(
            ['|', ('mobile', 'in', msisdn_variants(self.msisdn)),
             ('phone', 'in', msisdn_variants(self.msisdn))], limit=1)
        candidate = self.env['chat2work.candidate'].create(dict({
            'name': partner.name if partner else False,
            'partner_id': partner.id or False,
            'phone': self.msisdn,
            'registered_via': self._channel,
            'whatsapp_opt_in': bool(d.get('whatsapp')),
            'id_number_hash': d['id_hash'],
            'id_number_encrypted': d['id_enc'],
            'employment_status': d['employment'],
            'job_seeking': job_seeking,
            'consent_at': d['consent_at'],
            'status_updated_at': fields.Datetime.now(),
        }, **self._candidate_extra_vals()))
        self._set(created_candidate_id=candidate.id)
        if not self.env.context.get('chat2work_ussd_simulation'):
            self._after_profile_created(candidate)
        return self._profile_created_text(candidate), True

    def _after_profile_created(self, candidate):
        """Send the CV link. USSD can't show a link, so it goes by WhatsApp
        template or SMS after the session ends (queued, so the USSD gateway
        isn't kept waiting)."""
        candidate._c2w_queue_cv_link()

    def _profile_created_text(self, candidate):
        channel = "WhatsApp/SMS" if candidate.whatsapp_opt_in else "SMS"
        return "Profile created! We will contact you soon via %s." % channel

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
            if inp == '1':
                return self._ask_preferences()
            return "Status updated. Thank you! We will be in touch soon.", True
        if inp == '0':
            return self._goto('S08')
        return None

    # Terminal screens
    def _end_callback(self):
        self.env['chat2work.callback.request'].request_callback(
            partner=self.candidate_id.partner_id or None, phone=self.msisdn, channel=self._channel)
        return ("Callback requested for %s. A contact centre agent will call you shortly."
                % display_msisdn(self.msisdn)), True

    def _end_exit(self):
        return "Session ended. %s to start again." % self._restart(), True


class Chat2workUssdSession(models.Model):
    _name = 'chat2work.ussd.session'
    _inherit = 'chat2work.flow'
    _description = 'Chat2Work USSD Session'
    _order = 'create_date desc'
    _rec_name = 'session_id'

    session_id = fields.Char(required=True, index=True, readonly=True)
    service_code = fields.Char(readonly=True)
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
                inp = (latest_input or '').strip()
                session._note_input(inp)
                body, end = session._advance(inp)
            session._note('outbound', body)
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

    def _code(self):
        return self.service_code or self._param('ussd_service_code', '')

    def _restart_phrase(self):
        return "dial %s" % self._code()

    def _t_timeout(self, code):
        return "Session expired. Dial %s to start again." % code


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
