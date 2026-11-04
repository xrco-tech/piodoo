# -*- coding: utf-8 -*-
"""Whether a person has allowed one of our WhatsApp numbers to call them.

Meta enforces this; the record is our own copy so agents hear about a reply and
are warned before dialling. It can go stale (people can withdraw permission in
WhatsApp itself), so it warns rather than blocks and Meta keeps the final say.
"""

import json
import logging
import re
from datetime import datetime, timezone

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

REPLY_TYPE = 'call_permission_reply'
DEFAULT_PERMISSION_TEMPLATE = 'call_permission_request'
STATES = [
    ('pending', 'Waiting for reply'),
    ('granted', 'Allowed'),
    ('declined', 'Declined'),
    ('expired', 'No longer valid'),
]


class WhatsAppCallPermission(models.Model):
    _name = 'whatsapp.call.permission'
    _description = 'WhatsApp Call Permission'
    _order = 'write_date desc'
    _rec_name = 'phone'

    phone = fields.Char(required=True, index=True, readonly=True, help="Digits only, with country code.")
    phone_number_id = fields.Char('Business Number ID', required=True, index=True, readonly=True)
    partner_id = fields.Many2one('res.partner', 'Contact', ondelete='set null', readonly=True)
    state = fields.Selection(STATES, required=True, default='pending', readonly=True)
    current_state = fields.Selection(STATES, 'Status', compute='_compute_current_state')
    is_permanent = fields.Boolean(readonly=True)
    expires_at = fields.Datetime(readonly=True)
    response_source = fields.Selection([('user_action', 'The person'), ('automatic', 'WhatsApp, automatically')],
                                       'Answered By', readonly=True)
    requested_at = fields.Datetime(readonly=True)
    requested_by_id = fields.Many2one('res.users', 'Requested By', ondelete='set null', readonly=True)
    responded_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ('phone_number_uniq', 'unique(phone, phone_number_id)', 'One permission per person and business number.'),
    ]

    @api.depends('state', 'expires_at')
    def _compute_current_state(self):
        now = fields.Datetime.now()
        for rec in self:
            lapsed = rec.state == 'granted' and rec.expires_at and rec.expires_at <= now
            rec.current_state = 'expired' if lapsed else rec.state

    # ── Lookups ──────────────────────────────────────────────────────────────

    @api.model
    def _normalise_phone(self, phone):
        digits = re.sub(r'\D', '', phone or '')
        # Agents type local numbers; Meta sends international ones. All our
        # numbers are South African.
        return '27' + digits[1:] if len(digits) == 10 and digits.startswith('0') else digits

    @api.model
    def _resolve_account(self, account_id=None):
        Account = self.env['comm.whatsapp.account'].sudo()
        account = Account.browse(int(account_id)) if account_id else Account
        return account if account.exists() else Account.get_default()

    @api.model
    def _find(self, phone, phone_number_id):
        phone = self._normalise_phone(phone)
        if not phone or not phone_number_id:
            return self.browse()
        return self.sudo().search([('phone', '=', phone), ('phone_number_id', '=', phone_number_id)], limit=1)

    def _get_or_create(self, phone, phone_number_id):
        return self._find(phone, phone_number_id) or self.sudo().create({
            'phone': self._normalise_phone(phone), 'phone_number_id': phone_number_id})

    def _format_date(self, value):
        return fields.Datetime.context_timestamp(self, value).strftime('%d %b %Y %H:%M') if value else ''

    def _describe(self, name):
        """The sentence an agent sees about this permission."""
        self.ensure_one()
        state = self.current_state
        name = name or self.phone
        if state == 'pending':
            return _("A call permission request was sent to %(name)s on %(date)s and they haven't replied yet.",
                     name=name, date=self._format_date(self.requested_at))
        if state == 'declined' and self.response_source == 'automatic':
            return _("WhatsApp automatically turned off call permission for %(name)s on %(date)s. "
                     "This wasn't their own choice, so you can ask again.",
                     name=name, date=self._format_date(self.responded_at))
        if state == 'declined':
            return _("%(name)s declined calls from this number on %(date)s.",
                     name=name, date=self._format_date(self.responded_at))
        if state == 'expired':
            return _("Call permission from %(name)s is no longer valid. Ask them again before calling.", name=name)
        if self.is_permanent or not self.expires_at:
            return _("%(name)s allowed calls from this number.", name=name)
        return _("%(name)s allowed calls from this number until %(date)s.",
                 name=name, date=self._format_date(self.expires_at))

    @api.model
    def _status_for(self, phone, account_id=None, name=None):
        account = self._resolve_account(account_id)
        record = self._find(phone, account.phone_number_id)
        if not record:
            return {'state': False, 'message': False, 'declined_by_person': False}
        return {
            'state': record.current_state,
            'message': record._describe(name),
            'declined_by_person': record.current_state == 'declined' and record.response_source != 'automatic',
        }

    # ── Requesting ───────────────────────────────────────────────────────────

    @api.model
    def _permission_template(self, account):
        """The approved template to ask with: the one named in
        comm_whatsapp_calling.permission_template if it's approved, else
        call_permission_request. The account's own copy wins over another's."""
        Template = self.env['whatsapp.template'].sudo()
        preferred = self.env['ir.config_parameter'].sudo().get_param('comm_whatsapp_calling.permission_template')
        for name in filter(None, (preferred, DEFAULT_PERMISSION_TEMPLATE)):
            domain = [('name', '=ilike', name), ('status', '=', 'APPROVED')]
            template = (Template.search(domain + [('account_id', '=', account.id)], limit=1) if account
                        else Template) or Template.search(domain, limit=1)
            if template:
                return template
        return Template

    @api.model
    def _send_request(self, to_number, account_id=None, partner_name=None, partner_id=None):
        """Send the permission template. {"success": False, "error":
        "template_missing"} when no approved one exists, so the UI can show an
        actionable message instead of silently failing."""
        account = self._resolve_account(account_id)
        template = self._permission_template(account)
        if not template:
            return {'success': False, 'error': 'template_missing'}

        # Best-effort: if the body has exactly one named placeholder, assume
        # it's meant for the recipient's name. Multiple named placeholders have
        # no reliable mapping from a phone number and a display name, so they
        # fall back to _send_simple's generic per-parameter default. `_default`
        # covers the older numbered {{1}}, {{2}}.. style the same way.
        variables = {}
        named_params = template._extract_named_params()
        if len(named_params) == 1 and partner_name:
            variables[named_params[0]] = partner_name
        if partner_name:
            variables['_default'] = partner_name

        result = template._send_simple(to_number, variables=variables)
        phone_number_id = template.account_id.phone_number_id or account.phone_number_id
        if result.get('success') and phone_number_id:
            record = self._get_or_create(to_number, phone_number_id)
            record.write({
                'state': 'pending', 'is_permanent': False, 'expires_at': False, 'response_source': False,
                'responded_at': False, 'requested_at': fields.Datetime.now(), 'requested_by_id': self.env.uid,
                'partner_id': partner_id or record.partner_id.id,
            })
            record._post_note(_("Call permission request sent."))
        return result

    @api.model
    def _mark_not_approved(self, phone, phone_number_id):
        """Meta refused a dial for lack of permission, so an "Allowed" here is out of date."""
        record = self._find(phone, phone_number_id)
        if record and record.current_state == 'granted':
            record.write({'state': 'expired'})
            record._post_note(_("WhatsApp refused a call: call permission is no longer valid."))

    # ── Replies ──────────────────────────────────────────────────────────────

    def _apply_payload(self, message, reply):
        """Store one reply. Returns False for a repeat or out-of-order delivery."""
        self.ensure_one()
        when = message.message_timestamp or fields.Datetime.now()
        if self.responded_at and self.responded_at >= when:
            return False
        expiry = reply.get('expiration_timestamp')
        try:
            expires_at = datetime.fromtimestamp(int(expiry), tz=timezone.utc).replace(tzinfo=None) if expiry else False
        except (TypeError, ValueError):
            expires_at = False
        source = reply.get('response_source')
        accepted = reply.get('response') == 'accept'
        self.write({
            'state': 'granted' if accepted else 'declined',
            'is_permanent': accepted and bool(reply.get('is_permanent')),
            'expires_at': accepted and expires_at,
            'response_source': source if source in ('user_action', 'automatic') else False,
            'responded_at': when,
        })
        return True

    @api.model
    def _reply_from_message(self, message):
        try:
            return (json.loads(message.interactive_data or '{}') or {}).get(REPLY_TYPE) or {}
        except ValueError:
            return {}

    @api.model
    def _process_reply(self, message):
        """A person answered: save it and tell whoever asked."""
        reply = self._reply_from_message(message)
        if not reply or not message.phone_number_id:
            _logger.warning("comm_whatsapp_calling: unusable call permission reply in message %s", message.id)
            return self.browse()
        record = self._get_or_create(message.wa_id, message.phone_number_id)
        if record._apply_payload(message, reply):
            record._announce()
        return record

    def _announce(self):
        self.ensure_one()
        self._post_note(self._describe(self._display_person()))
        self._after_reply()
        if self.requested_by_id:
            self.env['bus.bus'].sudo()._sendone(self.requested_by_id.partner_id, 'whatsapp_call_permission', {
                'state': self.current_state, 'message': self.with_user(self.requested_by_id)._describe(self._display_person()),
            })

    def _display_person(self):
        return self.partner_id.name or self.phone

    def _post_note(self, body):
        """Hook: Chat2Work adds the candidate's chatter."""
        self.ensure_one()
        if self.partner_id:
            self.partner_id.sudo().message_post(body=body)

    def _after_reply(self):
        """Hook: for modules that follow up on a reply."""

    @api.model
    def _backfill_from_messages(self):
        """Replies received before this model existed. Quiet: they are old news."""
        messages = self.env['whatsapp.message'].sudo().search(
            [('interactive_type', '=', REPLY_TYPE), ('is_incoming', '=', True)], order='message_timestamp, id')
        for message in messages:
            reply = self._reply_from_message(message)
            if reply and message.wa_id and message.phone_number_id:
                self._get_or_create(message.wa_id, message.phone_number_id)._apply_payload(message, reply)
