# -*- coding: utf-8 -*-
"""ID checks through VerifyNow (https://www.verifynow.co.za/api-docs).

The API key is the system parameter chat2work.verifynow_api_key. Sandbox results
are mock data, so only production results ever touch the candidate. Only the
identity fields are kept, never the raw response, and the ID number is never
stored or logged here. Checks stay as a credit record after a candidate is
deleted, with everything personal removed.
"""

import logging
import uuid
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.chat2work.models.chat2work_ussd import ID_LIKE, ID_REDACTED

_logger = logging.getLogger(__name__)

BASE_URL = 'https://www.verifynow.co.za/api/external'
API_KEY_PARAM = 'chat2work.verifynow_api_key'
REQUEST_TIMEOUT = 60
IDEMPOTENCY_HOURS = 72
VALID_STATUS = 'ID Number Valid'
AUTO_BATCH = 50
ERRORS = {
    400: "VerifyNow rejected the request.",
    401: "The VerifyNow API key was refused.",
    402: "Not enough VerifyNow credits.",
    409: "VerifyNow reported a repeated request that doesn't match.",
    429: "VerifyNow is rate limiting. Try again shortly.",
}
ID_CHECK_STATES = [
    ('none', 'Not checked'),
    ('verified', 'Verified'),
    ('not_valid', 'Not valid'),
    ('failed', 'Check failed'),
]
PERSONAL_FIELDS = ('first_names', 'last_name', 'dob', 'age', 'gender', 'citizenship', 'id_status', 'error')


class Chat2workVerifyService(models.Model):
    _name = 'chat2work.verify.service'
    _description = 'VerifyNow Service'
    _order = 'name'

    name = fields.Char(required=True)
    report_type = fields.Char(required=True, help="VerifyNow's reportType for this service.")
    credits = fields.Float(required=True, help="Credits one production check costs.")
    active = fields.Boolean(default=True)

    _sql_constraints = [('report_type_unique', 'UNIQUE(report_type)', 'This service already exists.')]


class Chat2workVerifyCheck(models.Model):
    _name = 'chat2work.verify.check'
    _description = 'Chat2Work ID Check'
    _order = 'id desc'
    _rec_name = 'request_id'

    candidate_id = fields.Many2one('chat2work.candidate', ondelete='set null', index=True, readonly=True)
    service_id = fields.Many2one('chat2work.verify.service', required=True, ondelete='restrict', readonly=True)
    user_id = fields.Many2one('res.users', 'Run By', readonly=True, default=lambda self: self.env.uid)
    mode = fields.Selection([('sandbox', 'Sandbox'), ('production', 'Production')], required=True, readonly=True)
    state = fields.Selection([('verified', 'Verified'), ('not_valid', 'Not valid'), ('failed', 'Failed')],
                             readonly=True, index=True)
    idempotency_key = fields.Char(readonly=True, copy=False)
    request_id = fields.Char('Request', readonly=True)
    transaction_id = fields.Char(readonly=True)
    credits_used = fields.Float(readonly=True)
    credits_remaining = fields.Float(readonly=True)
    first_names = fields.Char(readonly=True)
    last_name = fields.Char(readonly=True)
    dob = fields.Date('Date of Birth', readonly=True)
    age = fields.Integer(readonly=True)
    gender = fields.Char(readonly=True)
    citizenship = fields.Char(readonly=True)
    id_status = fields.Char('ID Status', readonly=True)
    error = fields.Char(readonly=True)


class Chat2workVerifyAccount(models.Model):
    _name = 'chat2work.verify.account'
    _description = 'VerifyNow Account'

    name = fields.Char(required=True, readonly=True)
    mode = fields.Selection([('sandbox', 'Sandbox (mock data, no credits)'), ('production', 'Production (uses credits)')],
                            default='sandbox', required=True)
    auto_check = fields.Boolean('Check new candidates automatically',
                                help="Production only. Runs for candidates created after this is turned on.")
    auto_since = fields.Datetime(readonly=True)
    available_credits = fields.Float('Credits Remaining', readonly=True)
    balance_at = fields.Datetime('Balance Updated', readonly=True)
    low_credit_level = fields.Float('Warn Below', default=20)
    is_low = fields.Boolean(compute='_compute_usage')
    has_key = fields.Boolean('API Key Set', compute='_compute_usage')
    credits_used_total = fields.Float('Credits Used (All Time)', compute='_compute_usage')
    credits_used_month = fields.Float('Credits Used (This Month)', compute='_compute_usage')
    checks_total = fields.Integer('Production Checks', compute='_compute_usage')

    def _compute_usage(self):
        Check = self.env['chat2work.verify.check'].sudo()
        month = fields.Date.context_today(self).replace(day=1)
        production = Check.search([('mode', '=', 'production')])
        key = self.env['ir.config_parameter'].sudo().get_param(API_KEY_PARAM)
        for rec in self:
            rec.has_key = bool(key)
            rec.is_low = bool(rec.balance_at) and rec.available_credits < rec.low_credit_level
            rec.checks_total = len(production)
            rec.credits_used_total = sum(production.mapped('credits_used'))
            rec.credits_used_month = sum(c.credits_used for c in production if c.create_date.date() >= month)

    def write(self, vals):
        if vals.get('auto_check'):
            vals['auto_since'] = fields.Datetime.now()
        return super().write(vals)

    @api.model
    def _get(self):
        return self.env.ref('chat2work_verify.verify_account').sudo()

    def _api_key(self):
        key = (self.env['ir.config_parameter'].sudo().get_param(API_KEY_PARAM) or '').strip()
        if not key:
            raise UserError(_("Add the VerifyNow API key first (system parameter %s).", API_KEY_PARAM))
        return key

    def action_refresh_balance(self):
        self.ensure_one()
        try:
            response = requests.get(BASE_URL + '/my_credits', headers={'x-api-key': self._api_key()},
                                    timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            raise UserError(_("Couldn't reach VerifyNow.")) from e
        if response.status_code != 200:
            raise UserError(ERRORS.get(response.status_code, _("VerifyNow returned %s.", response.status_code)))
        self.sudo().write({'available_credits': response.json().get('available_credits') or 0,
                           'balance_at': fields.Datetime.now()})
        return True

    def _note_balance(self, remaining):
        self.sudo().write({'available_credits': remaining, 'balance_at': fields.Datetime.now()})

    @api.model
    def _cron_auto_checks(self):
        account = self._get()
        if not (account.auto_check and account.auto_since and account.mode == 'production' and account.has_key):
            return
        candidates = self.env['chat2work.candidate'].sudo().search([
            ('id_check_state', '=', 'none'), ('id_number_encrypted', '!=', False),
            ('create_date', '>=', account.auto_since),
        ], limit=AUTO_BATCH)
        for candidate in candidates:
            candidate._c2w_run_id_check()
            self.env.cr.commit()


class Chat2workCandidateVerify(models.Model):
    _inherit = 'chat2work.candidate'

    id_check_state = fields.Selection(ID_CHECK_STATES, 'ID Check', default='none', required=True, index=True,
                                      copy=False, readonly=True)
    id_check_at = fields.Datetime('ID Checked', copy=False, readonly=True)
    id_first_names = fields.Char('First Names (Home Affairs)', copy=False, readonly=True, groups='chat2work_verify.group_id_check')
    id_last_name = fields.Char('Surname (Home Affairs)', copy=False, readonly=True, groups='chat2work_verify.group_id_check')
    id_dob = fields.Date('Date of Birth (Home Affairs)', copy=False, readonly=True, groups='chat2work_verify.group_id_check')
    id_gender = fields.Char('Gender (Home Affairs)', copy=False, readonly=True, groups='chat2work_verify.group_id_check')
    id_citizenship = fields.Char('Citizenship (Home Affairs)', copy=False, readonly=True, groups='chat2work_verify.group_id_check')
    id_check_ids = fields.One2many('chat2work.verify.check', 'candidate_id', 'ID Checks',
                                   groups='chat2work_verify.group_id_check')

    def unlink(self):
        # Keep the credit record; nothing about the person stays with it.
        checks = self.env['chat2work.verify.check'].sudo().search([('candidate_id', 'in', self.ids)])
        checks.write(dict({f: False for f in PERSONAL_FIELDS}, candidate_id=False, idempotency_key=False))
        return super().unlink()

    def action_c2w_id_check(self):
        self.ensure_one()
        if not self.env.user.has_group('chat2work_verify.group_id_check'):
            raise UserError(_("You don't have access to run ID checks."))
        check = self.sudo()._c2w_run_id_check()
        message = {
            'verified': _("ID verified (%s mode).", check.mode),
            'not_valid': _("Home Affairs did not confirm this ID: %s", check.id_status or ''),
            'failed': _("The check didn't complete: %s You can try again without paying twice.", check.error or ''),
        }[check.state]
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("ID check"), 'message': message, 'sticky': check.state == 'failed',
                       'type': 'success' if check.state == 'verified' else 'warning',
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    def _c2w_id_check_record(self, service, mode):
        """A failed check within the idempotency window is retried with its own
        key, so a lost response can't be paid for twice."""
        cutoff = fields.Datetime.now() - timedelta(hours=IDEMPOTENCY_HOURS - 1)
        Check = self.env['chat2work.verify.check'].sudo()
        retry = Check.search([('candidate_id', '=', self.id), ('service_id', '=', service.id), ('mode', '=', mode),
                              ('state', '=', 'failed'), ('create_date', '>=', cutoff)], limit=1)
        return retry or Check.create({'candidate_id': self.id, 'service_id': service.id, 'mode': mode,
                                      'idempotency_key': str(uuid.uuid4())})

    def _c2w_run_id_check(self):
        self.ensure_one()
        rec = self.sudo()
        account = self.env['chat2work.verify.account']._get()
        service = self.env.ref('chat2work_verify.service_said').sudo()
        if not rec.id_number_encrypted:
            raise UserError(_("This candidate has no ID number."))
        mode = account.mode
        if mode == 'production' and rec.id_check_state in ('verified', 'not_valid'):
            raise UserError(_("This candidate has already been checked."))
        key = account._api_key()
        check = rec._c2w_id_check_record(service, mode)
        try:
            response = requests.post(BASE_URL + '/verify', timeout=REQUEST_TIMEOUT, headers={
                'x-api-key': key,
                'Content-Type': 'application/json',
                'Idempotency-Key': check.idempotency_key,
            }, json={'reportType': service.report_type, 'idNumber': rec._id_number_decrypt(), 'mode': mode})
        except requests.RequestException as e:
            # Not the exception text: it can include the request.
            _logger.warning("chat2work_verify: check %s: %s", check.id, type(e).__name__)
            return rec._c2w_id_check_failed(check, _("Couldn't reach VerifyNow."))
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or not data.get('success'):
            text = ERRORS.get(response.status_code) or str(data.get('error') or _("VerifyNow returned %s.", response.status_code))
            return rec._c2w_id_check_failed(check, ID_LIKE.sub(ID_REDACTED, text)[:200])
        return rec._c2w_id_check_done(check, service, account, data)

    def _c2w_id_check_failed(self, check, error):
        check.write({'state': 'failed', 'error': error})
        if check.mode == 'production':
            self.write({'id_check_state': 'failed', 'id_check_at': fields.Datetime.now()})
            self.message_post(body=_("ID check failed: %s", error))
        return check

    def _c2w_id_check_done(self, check, service, account, data):
        result = ((data.get('results') or {}).get(service.report_type) or {})
        realtime = result.get('realTimeResults') or {}
        person = realtime.get('Verification') or {}
        status = str(realtime.get('Status') or result.get('Status') or '')[:100]
        valid = status == VALID_STATUS
        remaining = data.get('remainingCredits')
        used = 0
        if check.mode == 'production':
            # Measured when possible: a repeat of a cached request costs nothing.
            used = service.credits
            if isinstance(remaining, (int, float)) and account.balance_at and account.available_credits >= remaining:
                used = account.available_credits - remaining
        try:
            dob = fields.Date.to_date(person.get('Dob')) if person.get('Dob') else False
        except ValueError:
            dob = False
        check.write({
            'state': 'verified' if valid else 'not_valid',
            'request_id': str(data.get('requestId') or '')[:100],
            'transaction_id': str(realtime.get('transaction_id') or result.get('transaction_id') or '')[:100],
            'credits_used': used,
            'credits_remaining': remaining if isinstance(remaining, (int, float)) else 0,
            'first_names': str(person.get('Firstnames') or '')[:120],
            'last_name': str(person.get('Lastname') or '')[:120],
            'dob': dob,
            'age': person.get('Age') if isinstance(person.get('Age'), int) else 0,
            'gender': str(person.get('Gender') or '')[:30],
            'citizenship': str(person.get('Citizenship') or '')[:60],
            'id_status': status,
            'error': False,
        })
        if isinstance(remaining, (int, float)) and check.mode == 'production':
            account._note_balance(remaining)
        if check.mode == 'production':
            self._c2w_apply_id_check(check)
        return check

    def _c2w_apply_id_check(self, check):
        vals = {'id_check_state': check.state, 'id_check_at': fields.Datetime.now()}
        if check.state == 'verified':
            vals.update(id_first_names=check.first_names, id_last_name=check.last_name, id_dob=check.dob,
                        id_gender=check.gender, id_citizenship=check.citizenship)
            full_name = ' '.join(filter(None, (check.first_names, check.last_name))).title()
            # Fill a missing name only; what the candidate gave us is theirs.
            if full_name and (not self.name or self.name == 'Candidate'):
                vals['name'] = full_name
        self.write(vals)
        self.message_post(body=_("ID check: %s.", check.id_status or check.state))
