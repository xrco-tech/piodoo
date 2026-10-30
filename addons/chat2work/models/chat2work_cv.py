# -*- coding: utf-8 -*-
"""The candidate's CV link: a personal URL to upload a CV, build one with a
guided form, or ask an agent for help.

After a profile is created the link goes out once:

- WhatsApp sessions get it in the conversation (a "cta_url" button), since the
  24-hour window is open.
- USSD sessions can't show links, so it's sent afterwards: by the approved
  WhatsApp template when the caller said their number is on WhatsApp, else by
  SMS. A WhatsApp send that fails, or isn't delivered within
  chat2work.cv_link_fallback_minutes, falls back to SMS.
"""

import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.modules import module as odoo_module

from .chat2work import _send_sms
from .chat2work_ussd import display_msisdn

_logger = logging.getLogger(__name__)


def _commit(env):
    """Commit between sends in the cron, so one failure doesn't resend the rest."""
    if not odoo_module.current_test:  # read at call time: tests set it after import
        env.cr.commit()


TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I: read out on calls
TOKEN_LENGTH = 10
LINK_DAYS = 30
FALLBACK_MINUTES = 15
CV_TEMPLATE = 'chat2work_cv_link'

LINK_STATES = [
    ('none', 'Not sent'),
    ('queued', 'Queued'),
    ('wa_sent', 'WhatsApp sent'),
    ('wa_delivered', 'WhatsApp delivered'),
    ('sms_queued', 'SMS fallback queued'),
    ('sms_sent', 'SMS sent'),
    ('failed', 'Failed'),
]
CV_STATES = [
    ('none', 'No CV yet'),
    ('started', 'Started, not finished'),
    ('uploaded', 'Uploaded'),
    ('built', 'Built with the form'),
    ('help_requested', 'Asked for help'),
]


class Chat2workCandidateCv(models.Model):
    _inherit = 'chat2work.candidate'

    cv_token = fields.Char(copy=False, index=True, readonly=True, groups='base.group_user')
    cv_token_expires = fields.Datetime('CV Link Expires', copy=False, readonly=True)
    cv_link_state = fields.Selection(LINK_STATES, 'CV Link', default='none', copy=False, readonly=True)
    cv_link_sent_at = fields.Datetime('CV Link Sent', copy=False, readonly=True)
    cv_link_wa_message_id = fields.Char(copy=False, readonly=True, index=True)
    cv_link_error = fields.Char('CV Link Error', copy=False, readonly=True)
    cv_state = fields.Selection(CV_STATES, 'CV', default='none', copy=False, readonly=True)
    cv_submitted_at = fields.Datetime('CV Submitted', copy=False, readonly=True)
    cv_data = fields.Json('CV Details', copy=False, readonly=True)
    cv_build_step = fields.Integer('CV Builder Step', copy=False, readonly=True,
                                   help="The step of the CV builder they last reached (1 to 5).")
    cv_attachment_id = fields.Many2one('ir.attachment', 'CV File', copy=False, readonly=True)
    cv_url = fields.Char('CV Page URL', compute='_compute_cv_url')
    source_tag = fields.Char('Campaign Source', readonly=True,
                             help="Tag from the WhatsApp start message, e.g. FLYER in 'Hi Chat2Work FLYER'.")

    def _c2w_display_phone(self):
        self.ensure_one()
        return display_msisdn(self.phone or '')

    def _compute_cv_url(self):
        for rec in self:
            rec.cv_url = rec._c2w_cv_url() if rec.sudo().cv_token else False

    # ── Activity log ─────────────────────────────────────────────────────────
    # No-ops here: chat2work_ucx writes them to the UCX workspace timeline.

    def _c2w_log_session(self, channel, transcript):
        """A finished USSD/WhatsApp session: [{'at', 'dir', 'text', 'wa'?}]."""

    def _c2w_log_event(self, channel, direction, body, status=None, wa_message_id=None):
        """One message or action outside a session (CV link sends, CV page)."""

    # ── Link ─────────────────────────────────────────────────────────────────

    def _c2w_base_url(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return (ICP.get_param('chat2work.public_base_url') or ICP.get_param('web.base.url') or '').rstrip('/')

    def _c2w_cv_url(self):
        self.ensure_one()
        return '%s/cv/%s' % (self._c2w_base_url(), self.sudo().cv_token)

    def _c2w_ensure_token(self):
        """Issue a fresh token if there's none or it has expired; returns it."""
        self.ensure_one()
        rec = self.sudo()
        if not rec.cv_token or not rec.cv_token_expires or rec.cv_token_expires < fields.Datetime.now():
            rec.write({
                'cv_token': ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH)),
                'cv_token_expires': fields.Datetime.now() + timedelta(days=LINK_DAYS),
            })
        return rec.cv_token

    @api.model
    def _c2w_find_by_token(self, token):
        """The active candidate for an unexpired token, else an empty recordset."""
        if not token or len(token) != TOKEN_LENGTH or set(token) - set(TOKEN_ALPHABET):
            return self.browse()
        return self.sudo().search([
            ('cv_token', '=', token),
            ('cv_token_expires', '>', fields.Datetime.now()),
        ], limit=1)

    # ── Sending ──────────────────────────────────────────────────────────────

    def _c2w_queue_cv_link(self):
        """Send the CV link after this transaction commits (by cron trigger)."""
        for rec in self:
            rec._c2w_ensure_token()
            rec.sudo().write({'cv_link_state': 'queued', 'cv_link_error': False})
        cron = self.env.ref('chat2work.ir_cron_chat2work_cv_links', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def action_resend_cv_link(self):
        self._c2w_queue_cv_link()
        return True

    def _c2w_sms_text(self):
        return ("Chat2Work: your profile is ready. Add your CV here: %s "
                "(valid %d days). We never ask for money." % (self._c2w_cv_url(), LINK_DAYS))

    def _c2w_send_sms_link(self):
        self.ensure_one()
        self._c2w_ensure_token()
        body = self._c2w_sms_text()
        ok = _send_sms(self.env, self.phone, body)
        self._c2w_log_event('sms', 'outbound', body, 'sent' if ok else 'failed')
        self.sudo().write({
            'cv_link_state': 'sms_sent' if ok else 'failed',
            'cv_link_sent_at': fields.Datetime.now(),
            'cv_link_error': False if ok else 'SMS could not be sent',
        })
        return ok

    def _c2w_cv_template(self):
        name = self.env['ir.config_parameter'].sudo().get_param('chat2work.cv_template', CV_TEMPLATE)
        return self.env['whatsapp.template'].sudo().search(
            [('name', '=', name), ('status', '=', 'APPROVED')], limit=1)

    def _c2w_send_wa_template_link(self):
        """Send the approved template with the token as the URL button suffix.
        Returns True when Meta accepted it."""
        self.ensure_one()
        template = self._c2w_cv_template()
        if not template:
            return False
        token = self._c2w_ensure_token()
        content = {
            'type': 'template',
            'template': {
                'name': template.name,
                'language': {'code': template.language},
                'components': [{
                    'type': 'button', 'sub_type': 'url', 'index': '0',
                    'parameters': [{'type': 'text', 'text': token}],
                }],
            },
        }
        res = self.env['whatsapp.message'].sudo().send_whatsapp_payload(
            self.phone, content, account=template.account_id or None,
            log_body='Template %s: %s' % (template.name, self._c2w_cv_url()), log_type='template')
        body = '%s\n[Add my CV] %s' % (template.body or '', self._c2w_cv_url())
        self._c2w_log_event('whatsapp', 'outbound', body, None if res.get('success') else 'failed',
                            res.get('message_id'))
        if not res.get('success'):
            self.sudo().cv_link_error = (res.get('error') or 'WhatsApp send failed')[:250]
            return False
        self.sudo().write({
            'cv_link_state': 'wa_sent',
            'cv_link_sent_at': fields.Datetime.now(),
            'cv_link_wa_message_id': res.get('message_id'),
            'cv_link_error': False,
        })
        return True

    def _c2w_send_cv_link_now(self):
        for rec in self:
            try:
                if rec.whatsapp_opt_in and rec._c2w_send_wa_template_link():
                    continue
                rec._c2w_send_sms_link()
            except Exception:
                _logger.exception("chat2work: CV link for candidate %s failed", rec.id)
                rec.sudo().write({'cv_link_state': 'failed', 'cv_link_error': 'Unexpected error'})

    @api.model
    def _cron_send_cv_links(self):
        """Send queued links, and fall back to SMS for WhatsApp ones that
        failed or weren't delivered in time."""
        Candidate = self.sudo()
        for rec in Candidate.search([('cv_link_state', '=', 'queued')], limit=200):
            rec._c2w_send_cv_link_now()
            _commit(self.env)
        minutes = int(self.env['ir.config_parameter'].sudo().get_param(
            'chat2work.cv_link_fallback_minutes', FALLBACK_MINUTES))
        stale = fields.Datetime.now() - timedelta(minutes=minutes)
        fallback = Candidate.search([
            '|', ('cv_link_state', '=', 'sms_queued'),
            '&', ('cv_link_state', '=', 'wa_sent'), ('cv_link_sent_at', '<', stale),
        ], limit=200)
        for rec in fallback:
            _logger.info("chat2work: CV link for candidate %s not delivered on WhatsApp; sending SMS", rec.id)
            rec._c2w_send_sms_link()
            _commit(self.env)

    # ── CV page actions ──────────────────────────────────────────────────────

    def _c2w_store_cv_file(self, filename, content, mimetype, state):
        self.ensure_one()
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'raw': content,
            'mimetype': mimetype,
            'res_model': self._name,
            'res_id': self.id,
        })
        self.sudo().write({
            'cv_attachment_id': attachment.id,
            'cv_state': state,
            'cv_submitted_at': fields.Datetime.now(),
        })
        self._c2w_touch()
        self._c2w_log_event('web', 'inbound', 'Built a CV with the CV page form: %s' % filename
                            if state == 'built' else 'Uploaded a CV on the CV page: %s' % filename)
        return attachment

    def _c2w_save_cv_draft(self, details, step):
        """Keep unfinished answers. Only someone with no CV yet becomes 'started':
        drafting a replacement doesn't undo a CV or help request they already have."""
        self.ensure_one()
        rec = self.sudo()
        first = rec.cv_state == 'none'
        vals = {'cv_data': details, 'cv_build_step': step}
        if first:
            vals['cv_state'] = 'started'
        rec.write(vals)
        self._c2w_touch()
        if first:
            self._c2w_log_event('web', 'inbound', 'Started building a CV on the CV page.')

    def _c2w_build_cv(self, details):
        """Save the form answers and render the standard CV as a PDF."""
        self.ensure_one()
        rec = self.sudo()
        rec.write({'cv_data': details, 'cv_build_step': 0})
        if details.get('full_name') and not rec.name:
            rec.name = details['full_name']
        if details.get('town') and not rec.location:
            rec.location = details['town']
        pdf, _ = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'chat2work.action_report_cv', res_ids=rec.ids)
        safe = ''.join(c for c in (details.get('full_name') or 'Candidate') if c.isalnum() or c == ' ').strip()
        return rec._c2w_store_cv_file('CV - %s.pdf' % (safe or 'Candidate'), pdf, 'application/pdf', 'built')

    def _c2w_request_cv_help(self):
        self.ensure_one()
        callback = self.env['chat2work.callback.request'].sudo().create({
            'partner_id': self.partner_id.id or False,
            'phone': self.phone,
            'candidate_id': self.id,
            'channel': 'cv_page',
            'notes': 'Asked for help creating a CV (from the CV page).',
        })
        self.sudo().write({'cv_state': 'help_requested', 'cv_submitted_at': fields.Datetime.now()})
        self._c2w_touch()
        self._c2w_log_event('web', 'inbound', 'Asked for help creating a CV (CV page). Callback request logged.')
        return callback


class WhatsAppMessageCvStatus(models.Model):
    """Track the CV-link template's delivery: delivered/read settles it, failed
    queues the SMS fallback straight away."""
    _inherit = 'whatsapp.message'

    def write(self, vals):
        res = super().write(vals)
        status = vals.get('message_status')
        if status in ('delivered', 'read', 'failed'):
            ids = [m for m in self.mapped('message_id') if m]
            if ids:
                Candidate = self.env['chat2work.candidate'].sudo()
                cands = Candidate.search([
                    ('cv_link_wa_message_id', 'in', ids), ('cv_link_state', '=', 'wa_sent')])
                if cands and status == 'failed':
                    cands.write({'cv_link_state': 'sms_queued', 'cv_link_error': 'WhatsApp delivery failed'})
                    cron = self.env.ref('chat2work.ir_cron_chat2work_cv_links', raise_if_not_found=False)
                    if cron:
                        cron.sudo()._trigger()
                elif cands:
                    cands.write({'cv_link_state': 'wa_delivered'})
        return res
