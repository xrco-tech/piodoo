# -*- coding: utf-8 -*-
"""Telling candidates about jobs agents matched them to.

Only an agent's "Good match" on a verified listing queues anything, so nobody
hears about a job a person hasn't checked. A cron sends one alert per
candidate, at most every few days and only in the daytime, covering all their
waiting matches:

- WhatsApp inside the 24-hour window: a message with "See my job matches" and
  "Not now" buttons; outside it the approved template with the same buttons.
- Not on WhatsApp: an SMS saying an agent will call.

"See my job matches" sends a list of their open matches. Tapping a job marks
them interested and logs a callback request, so an agent calls; "None of
these" marks the listed ones not interested. Returning candidates can also
choose "My job matches" from the WhatsApp welcome-back menu.
"""

import logging
import re
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from odoo.addons.chat2work.models.chat2work import _send_sms
from odoo.addons.chat2work.models.chat2work_cv import _commit
from odoo.addons.chat2work.models.chat2work_ussd import first_name, msisdn_variants, normalize_msisdn

from .chat2work_listing import UNAVAILABLE_STAGES

_logger = logging.getLogger(__name__)

JOB_TEMPLATE = 'chat2work_job_match'
GAP_DAYS = 3
SEND_HOURS = (8, 19)  # local time: from 08:00, until 19:00
TZ = 'Africa/Johannesburg'
BATCH = 50
LIST_MAX = 9  # plus the "None of these" row: WhatsApp lists hold 10
ROW_TITLE_MAX = 24
ROW_DESC_MAX = 72
SEE = 'c2w:jobs'
LATER = 'c2w:jobs_later'
PICK = 'c2w:job:'
NONE = PICK + 'none'
FOOTER = 'Chat2Work never asks for money.'


class Chat2workListingMatchComms(models.Model):
    _inherit = 'chat2work.listing.match'

    notify_state = fields.Selection([
        ('none', 'Not sent'),
        ('queued', 'Waiting to send'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('cancelled', 'Not sent'),
    ], 'Candidate Told', default='none', required=True, copy=False, readonly=True, index=True)
    notified_at = fields.Datetime('Told At', copy=False, readonly=True)
    response = fields.Selection([('interested', 'Interested'), ('not_interested', 'Not interested')],
                                'Candidate Reply', copy=False, readonly=True)
    responded_at = fields.Datetime('Replied At', copy=False, readonly=True)

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'approved':
            self.filtered(lambda m: m.notify_state == 'none').sudo().write({'notify_state': 'queued'})
        elif vals.get('state') in ('suggested', 'rejected'):
            self.filtered(lambda m: m.notify_state == 'queued').sudo().write({'notify_state': 'none'})
        return res

    def _c2w_row(self):
        listing = self.listing_id
        where = ' · '.join(filter(None, (listing.location or ', '.join(listing.province_ids.mapped('name')),
                                         listing.employer)))
        return {'id': PICK + str(self.id), 'title': listing.title[:ROW_TITLE_MAX],
                'description': (where or listing.title)[:ROW_DESC_MAX]}

    def _c2w_label(self):
        listing = self.listing_id
        return '%s%s' % (listing.title, ' (%s)' % listing.location if listing.location else '')

    @api.model
    def _c2w_in_send_hours(self):
        hour = datetime.now(pytz.timezone(TZ)).hour
        return SEND_HOURS[0] <= hour < SEND_HOURS[1]

    @api.model
    def _cron_send_job_alerts(self):
        if not self._c2w_in_send_hours():
            return
        gap = int(self.env['ir.config_parameter'].sudo().get_param('chat2work.job_alert_gap_days', GAP_DAYS))
        recent = fields.Datetime.now() - timedelta(days=gap)
        queued = self.sudo().search([('notify_state', '=', 'queued')], order='id')
        stale = queued.filtered(lambda m: m.state != 'approved' or m.listing_id.state != 'open'
                                or m.candidate_id.stage in UNAVAILABLE_STAGES)
        stale.write({'notify_state': 'cancelled'})
        sent = 0
        for candidate in (queued - stale).candidate_id:
            if sent >= BATCH:
                break
            if candidate.job_alert_at and candidate.job_alert_at > recent:
                continue
            matches = (queued - stale).filtered(lambda m: m.candidate_id == candidate)
            try:
                ok = candidate._c2w_send_job_alert(matches)
            except Exception:  # noqa: BLE001 - one failure mustn't stop the rest
                _logger.exception("chat2work_jobs: job alert for candidate %s failed", candidate.id)
                ok = False
            now = fields.Datetime.now()
            matches.write({'notify_state': 'sent' if ok else 'failed', 'notified_at': now})
            if ok:
                candidate.job_alert_at = now
                sent += 1
            _commit(self.env)


class Chat2workCandidateJobComms(models.Model):
    _inherit = 'chat2work.candidate'

    job_alert_at = fields.Datetime('Last Job Alert', copy=False, readonly=True)

    def _c2w_open_job_matches(self):
        """Matches they've been told about and haven't answered, newest first."""
        self.ensure_one()
        return self.listing_match_ids.sudo().filtered(
            lambda m: m.state == 'approved' and m.notify_state == 'sent' and not m.response
            and m.listing_id.state == 'open').sorted('notified_at', reverse=True)

    def _c2w_job_alert_text(self, count):
        name = first_name(self.name)
        what = 'a job' if count == 1 else '%d jobs' % count
        return ("Hi%s, good news: we found %s that may suit you. Tap below to see %s and tell us if you're "
                "interested." % (' ' + name if name else '', what, 'it' if count == 1 else 'them'))

    def _c2w_send_job_alert(self, matches, channel=None):
        """Tell the candidate about `matches`. Returns True when it went out.

        `channel` is 'whatsapp' or 'sms' when an agent picked one; otherwise
        WhatsApp if they use it, falling back to SMS."""
        self.ensure_one()
        text = self._c2w_job_alert_text(len(matches))
        if self.whatsapp_opt_in and channel != 'sms':
            Message = self.env['whatsapp.message'].sudo()
            res = None
            if self._c2w_wa_window_open():
                res = Message.send_whatsapp_payload(self.phone, {
                    'type': 'interactive',
                    'interactive': {
                        'type': 'button',
                        'body': {'text': text},
                        'footer': {'text': FOOTER},
                        'action': {'buttons': [
                            {'type': 'reply', 'reply': {'id': SEE, 'title': 'See my job matches'}},
                            {'type': 'reply', 'reply': {'id': LATER, 'title': 'Not now'}},
                        ]},
                    },
                }, log_body=text, log_type='interactive')
            else:
                template = self.env['whatsapp.template'].sudo().search(
                    [('name', '=', JOB_TEMPLATE), ('status', '=', 'APPROVED')], limit=1)
                if template:
                    res = Message.send_whatsapp_payload(self.phone, {
                        'type': 'template',
                        'template': {
                            'name': template.name,
                            'language': {'code': template.language},
                            'components': [
                                {'type': 'body', 'parameters': [
                                    {'type': 'text', 'text': first_name(self.name) or 'there'}]},
                                {'type': 'button', 'sub_type': 'quick_reply', 'index': '0',
                                 'parameters': [{'type': 'payload', 'payload': SEE}]},
                                {'type': 'button', 'sub_type': 'quick_reply', 'index': '1',
                                 'parameters': [{'type': 'payload', 'payload': LATER}]},
                            ],
                        },
                    }, account=template.account_id or None, log_body=text, log_type='template')
            if res is not None:
                self._c2w_log_event('whatsapp', 'outbound', text, None if res.get('success') else 'failed',
                                    res.get('message_id'))
                if res.get('success'):
                    return True
            if channel == 'whatsapp':
                return False
        jobs = ', '.join(m._c2w_label() for m in matches[:2])
        sms = ("Chat2Work: we found work that may suit you: %s. An agent will call you about it. "
               "We never ask for money." % jobs)
        ok = _send_sms(self.env, self.phone, sms)
        self._c2w_log_event('sms', 'outbound', sms, 'sent' if ok else 'failed')
        return ok


class Chat2workWaSessionJobs(models.Model):
    _inherit = 'chat2work.wa.session'

    # ── Welcome-back menu: "My job matches" ──────────────────────────────────

    def _screen(self, screen):
        prompt, options = super()._screen(screen)
        if screen == 'S01A' and self.candidate_id and self.candidate_id._c2w_open_job_matches():
            options = [o for o in options if o[0] != '0'] + [('3', 'My job matches'), ('0', 'Exit')]
        return prompt, options

    def _on_S01A(self, inp):
        if inp == '3' and self.candidate_id._c2w_open_job_matches():
            self._set(show_jobs=True)
            return "Here are the jobs we matched you to.", True
        return super()._on_S01A(inp)

    def _send_turn(self, body, end):
        show = end and (self.data or {}).get('show_jobs') and self.candidate_id
        wa_id, account = self.wa_id, self.account_id
        res = super()._send_turn(body, end)
        if show:
            self._c2w_send_job_list(wa_id, account, show)
        return res

    # ── Replies to the alert and the list ────────────────────────────────────

    @api.model
    def wa_handle(self, webhook_message, value_data):
        inp, _is_text = self._reply_input(webhook_message)
        if inp in (SEE, LATER) or inp.startswith(PICK):
            phone_number_id = ((value_data or {}).get('metadata') or {}).get('phone_number_id')
            account = self.env['comm.whatsapp.account'].sudo().find_for_phone_number_id(phone_number_id)
            if self._account_allowed(account):
                wa_id = re.sub(r'\D', '', webhook_message.get('from') or '')
                self.sudo()._c2w_job_reply(wa_id, account, inp)
                return True
        return super().wa_handle(webhook_message, value_data)

    @api.model
    def _c2w_text(self, wa_id, account, text):
        self.env['whatsapp.message'].sudo().send_whatsapp_payload(
            wa_id, {'type': 'text', 'text': {'body': text}}, account=account or None, log_body=text, log_type='text')

    @api.model
    def _c2w_send_job_list(self, wa_id, account, candidate):
        matches = candidate._c2w_open_job_matches()
        if not matches:
            self._c2w_text(wa_id, account, "There are no open job matches for you right now. We'll let you know "
                                           "when we find something that suits you.")
            return
        rows = [m._c2w_row() for m in matches[:LIST_MAX]] + [
            {'id': NONE, 'title': 'None of these', 'description': "Not interested in these jobs"}]
        body = "Tap a job you're interested in, and an agent will call you about it."
        self.env['whatsapp.message'].sudo().send_whatsapp_payload(wa_id, {
            'type': 'interactive',
            'interactive': {
                'type': 'list',
                'body': {'text': body},
                'footer': {'text': FOOTER},
                'action': {'button': 'See jobs', 'sections': [{'title': 'Your job matches', 'rows': rows}]},
            },
        }, account=account or None, log_body=body + ' ' + ', '.join(r['title'] for r in rows), log_type='interactive')
        candidate._c2w_log_event('whatsapp', 'outbound', 'Job matches list: %s' % ', '.join(
            m._c2w_label() for m in matches[:LIST_MAX]))

    @api.model
    def _c2w_job_reply(self, wa_id, account, inp):
        candidate = self.env['chat2work.candidate'].sudo().search(
            [('phone', 'in', msisdn_variants(normalize_msisdn(wa_id)))], limit=1)
        if not candidate:
            self._c2w_text(wa_id, account, 'Send "Ispani" to start with Chat2Work.')
            return
        now = fields.Datetime.now()
        if inp == SEE:
            self._c2w_send_job_list(wa_id, account, candidate)
        elif inp == LATER:
            candidate._c2w_log_event('whatsapp', 'inbound', 'Job alert: Not now')
            self._c2w_text(wa_id, account, 'No problem. To see your job matches later, send "Ispani" and choose '
                                           '"My job matches".')
        elif inp == NONE:
            shown = candidate._c2w_open_job_matches()[:LIST_MAX]
            shown.write({'response': 'not_interested', 'responded_at': now})
            candidate.message_post(body="Not interested in: %s" % ', '.join(m._c2w_label() for m in shown))
            candidate._c2w_log_event('whatsapp', 'inbound', 'Job matches: none of these')
            self._c2w_text(wa_id, account, "Thanks for letting us know. We'll keep looking for something that "
                                           "suits you.")
        else:
            match = self.env['chat2work.listing.match'].sudo().browse(int(inp[len(PICK):] or 0)).exists() \
                if inp[len(PICK):].isdigit() else self.env['chat2work.listing.match']
            if not match or match.candidate_id != candidate or match.state != 'approved':
                self._c2w_text(wa_id, account, "Sorry, that job isn't available any more.")
                return
            if match.response != 'interested':
                match.write({'response': 'interested', 'responded_at': now})
                label = match._c2w_label()
                self.env['chat2work.callback.request'].sudo().create({
                    'partner_id': candidate.partner_id.id or False,
                    'phone': candidate.phone,
                    'candidate_id': candidate.id,
                    'channel': 'whatsapp',
                    'notes': 'Interested in a job match: %s, %s' % (label, match.listing_id.employer or
                                                                   'employer not stated'),
                })
                candidate.message_post(body="Interested in job match: %s" % label)
                candidate._c2w_log_event('whatsapp', 'inbound', 'Interested in job: %s' % label)
            text = ("Great! We've told the team you're interested in %s. An agent will call you about it soon. "
                    "Chat2Work never asks for money." % match.listing_id.title)
            if candidate._c2w_open_job_matches():
                self.env['whatsapp.message'].sudo().send_whatsapp_payload(wa_id, {
                    'type': 'interactive',
                    'interactive': {'type': 'button', 'body': {'text': text}, 'action': {'buttons': [
                        {'type': 'reply', 'reply': {'id': SEE, 'title': 'See other matches'}}]}},
                }, account=account or None, log_body=text, log_type='interactive')
            else:
                self._c2w_text(wa_id, account, text)
