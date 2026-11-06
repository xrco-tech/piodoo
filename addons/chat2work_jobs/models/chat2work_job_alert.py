# -*- coding: utf-8 -*-
"""One job per message, with the candidate's verdict on the match.

Each alert names the role, employer, area and closing date, with a short
link (/j/<token>) that counts the open and goes straight to the employer's
application. The candidate says whether it's a good match:

- WhatsApp: "Good match", "Not for me" and "Stop job alerts" buttons. A normal
  message inside the 24-hour window, else the chat2work_job_alert template.
- SMS: reply 1 (good match) or 2 (not), or STOP. One SMS, plain characters:
  the title always, the employer and area when they fit.

Every alert carries an opt-out (POPIA direct marketing). Stopped candidates
get nothing until they send START.

_c2w_send_top_jobs picks what to send without an agent: each candidate's
highest-scoring jobs on verified, open listings with an apply link. The daily
cron does the same with a smaller number, and is off until switched on.
"""

import logging
import re
import secrets
import unicodedata
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.chat2work.models.chat2work import _send_sms
from odoo.addons.chat2work.models.chat2work_cv import _commit
from odoo.addons.chat2work.models.chat2work_ussd import first_name, msisdn_variants, normalize_msisdn

from .chat2work_listing import UNAVAILABLE_STAGES

_logger = logging.getLogger(__name__)

ALERT_TEMPLATE = 'chat2work_job_alert'
GOOD, BAD, STOP = 'c2w:jf:good:', 'c2w:jf:bad:', 'c2w:jf:stop'
FOOTER = 'Chat2Work never asks for money.'
NOT_STATED = 'See the link'
TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
TOKEN_LENGTH = 6
SMS_MAX = 160
SMS_REPLY_DAYS = 14
TOP_JOBS_MIN_SCORE = 3
WA_BODY = ("Hi {name} 👋 We found a job that matches your profile:\n\n"
           "💼 {title}\n🏢 {employer}\n📍 {location}\n📅 Apply by {closing}\n\n"
           "Apply here: {link}\n\nIs this a good match for you?")
THANKS_GOOD = "Great! Use the link to apply. Good luck 🍀"
THANKS_BAD = "Thanks for telling us. We'll use this to find you better matches."
STOPPED = ('Done. We won\'t send you job alerts any more. Reply START if you change your mind.')
STARTED = "Welcome back! We'll send you jobs that match your profile again."


def _plain(text):
    """GSM-safe text for SMS: no emoji, curly quotes or accents."""
    text = (text or '').replace('’', "'").replace('‘', "'").replace('–', '-').replace('—', '-')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return ' '.join(text.split())


def _param(text, limit=60):
    """A template variable: one line, no runs of spaces, never empty."""
    text = ' '.join((text or '').split())[:limit]
    return text or NOT_STATED


class Chat2workListingMatchAlert(models.Model):
    _inherit = 'chat2work.listing.match'

    notify_channel = fields.Selection([('whatsapp', 'WhatsApp'), ('sms', 'SMS')], 'Sent By', readonly=True,
                                      copy=False)
    feedback = fields.Selection([('good', 'Good match'), ('bad', 'Not for me')], 'Candidate Says', readonly=True,
                                copy=False, index=True)
    feedback_at = fields.Datetime(readonly=True, copy=False)
    link_token = fields.Char(readonly=True, copy=False, index=True)
    opened_at = fields.Datetime('Link First Opened', readonly=True, copy=False)
    open_count = fields.Integer('Link Opens', readonly=True, copy=False)

    _sql_constraints = [('link_token_unique', 'UNIQUE(link_token)', 'This job link already exists.')]

    def _c2w_link(self):
        self.ensure_one()
        if not self.link_token:
            self.sudo().link_token = ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
        return '%s/j/%s' % (self.candidate_id._c2w_base_url(), self.link_token)

    def _c2w_alert_parts(self):
        """The details an alert shows, each never empty."""
        self.ensure_one()
        listing = self.listing_id
        location = listing.location or ', '.join(listing.province_ids.mapped('name')[:2])
        if len(listing.province_ids) > 2 and not listing.location:
            location = 'Several provinces'
        return {
            'name': first_name(self.candidate_id.name) or 'there',
            'title': _param(re.split(r'\s[-–|]\s|\s\(', listing.title or '')[0]),
            'employer': _param(listing.employer),
            'location': _param(location),
            'closing': listing.closing_on.strftime('%-d %b') if listing.closing_on else NOT_STATED,
            'link': self._c2w_link(),
        }

    def _c2w_sms_text(self):
        """One SMS: the title always, then the employer and area if they fit."""
        parts = {k: _plain(v) for k, v in self._c2w_alert_parts().items()}
        link = re.sub(r'^https?://', '', parts['link'])
        closing = ' Apply by %s:' % parts['closing'] if parts['closing'] != NOT_STATED else ' Apply:'
        head = 'Chat2Work: Hi %s, a job for you: ' % parts['name'][:15]
        tail = '.%s %s Reply 1=good match, 2=not. STOP to opt out' % (closing, link)
        room = SMS_MAX - len(head) - len(tail)
        job = parts['title'][:room].rstrip()
        for extra in (' at %s' % parts['employer'], ', %s' % parts['location']):
            if NOT_STATED not in extra and len(job) + len(extra) <= room:
                job += extra
        return head + job + tail

    def _c2w_record_feedback(self, verdict, channel):
        self.ensure_one()
        if self.feedback == verdict:
            return
        self.sudo().write({'feedback': verdict, 'feedback_at': fields.Datetime.now()})
        label = dict(self._fields['feedback'].selection)[verdict]
        self.candidate_id.sudo().message_post(body="%s: %s" % (label, self._c2w_label()))
        self.candidate_id._c2w_log_event(channel, 'inbound', '%s: %s' % (label, self._c2w_label()))

    @api.model
    def _c2w_top_jobs(self, per_candidate, min_score=TOP_JOBS_MIN_SCORE, rescore=True):
        """{candidate: matches} to send now, best first.

        Suggested and Good matches on verified, open listings with an apply
        link that haven't closed, the candidate hasn't been sent or judged,
        and scoring at least `min_score` with today's rules. Candidates who
        stopped alerts, aren't looking, or already had one today get none.
        """
        today = fields.Date.context_today(self)
        start_of_day = fields.Datetime.now() - timedelta(hours=24)
        matches = self.sudo().search([
            ('state', '!=', 'rejected'), ('notify_state', '!=', 'sent'), ('feedback', '=', False),
            ('listing_id.state', '=', 'open'), ('listing_id.verification_state', '=', 'verified'),
            ('listing_id.apply_url', '!=', False), ('listing_id.apply_url', '!=', ''),
            '|', ('listing_id.closing_on', '=', False), ('listing_id.closing_on', '>=', today),
            ('candidate_id.job_seeking', '=', True), ('candidate_id.job_alerts_stopped', '=', False),
            ('candidate_id.stage', 'not in', UNAVAILABLE_STAGES), ('candidate_id.phone', '!=', False),
        ])
        picked = {}
        for candidate in matches.candidate_id:
            if candidate.listing_match_ids.filtered(lambda m: m.notified_at and m.notified_at > start_of_day):
                continue
            mine = matches.filtered(lambda m: m.candidate_id == candidate)
            if rescore:
                for match in mine:
                    result = match.listing_id._score_candidate(candidate)
                    score, reason = (result[0], '; '.join(result[1])) if result else (-1, 'no longer fits')
                    if (score, reason) != (match.score, match.reason):
                        match.write({'score': score, 'reason': reason})
            best = mine.filtered(lambda m: m.score >= min_score).sorted(
                lambda m: (-m.score, m.listing_id.closing_on or fields.Date.today() + timedelta(days=365), m.id))
            if best:
                picked[candidate] = best[:per_candidate]
        return picked

    @api.model
    def _c2w_send_top_jobs(self, per_candidate, min_score=TOP_JOBS_MIN_SCORE, sms_fallback=True):
        """Send each candidate their best jobs, one message each. Returns (sent, failed, waiting):
        waiting are WhatsApp candidates held back while the template can't be used and
        `sms_fallback` is off."""
        sent = failed = waiting = 0
        for candidate, matches in self._c2w_top_jobs(per_candidate, min_score).items():
            for match in matches:
                try:
                    ok = candidate._c2w_send_job_listing(match, sms_fallback=sms_fallback)
                except Exception:  # noqa: BLE001 - one failure mustn't stop the rest
                    _logger.exception("chat2work_jobs: job alert %s failed", match.id)
                    ok = False
                if ok is None:
                    waiting += 1
                    continue
                sent, failed = sent + ok, failed + (not ok)
                _commit(self.env)
        return sent, failed, waiting

    @api.model
    def _cron_send_daily_jobs(self):
        if not self._c2w_in_send_hours():
            return
        per_day = int(self.env['ir.config_parameter'].sudo().get_param('chat2work.job_alerts_per_day', 1))
        _logger.info("chat2work_jobs: daily job alerts: %s sent, %s failed, %s waiting for WhatsApp",
                     *self._c2w_send_top_jobs(per_day))


class Chat2workCandidateJobAlert(models.Model):
    _inherit = 'chat2work.candidate'

    job_alerts_stopped = fields.Boolean('Stopped Job Alerts', tracking=True, copy=False,
                                        help="They asked for no more job alerts (STOP). Untick if they ask again.")

    def _c2w_send_job_alert(self, matches, channel=None):
        """Each match in its own message. True when at least one went out."""
        sent = False
        for match in matches:
            sent = self._c2w_send_job_listing(match, channel) or sent
        return sent

    def _c2w_send_job_listing(self, match, channel=None, sms_fallback=True):
        """Send one job. `channel` is the agent's pick; otherwise the recommended one,
        falling back to SMS when WhatsApp can't go (unless `sms_fallback` is off:
        then it waits, returning None). Returns True when it went out."""
        self.ensure_one()
        if self.job_alerts_stopped:
            return False
        channel_given = channel
        channel = channel or self._c2w_recommended_channel()[0]
        parts = match._c2w_alert_parts()
        sent_by = None
        if channel == 'whatsapp' and self.whatsapp_opt_in:
            res = self._c2w_job_alert_whatsapp(match, parts)
            if res is not None:
                text = WA_BODY.format(**parts)
                self._c2w_log_event('whatsapp', 'outbound', text, None if res.get('success') else 'failed',
                                    res.get('message_id'))
                if res.get('success'):
                    sent_by = 'whatsapp'
            if not sent_by and channel_given == 'whatsapp':
                return False
            if res is None and not sms_fallback:
                return None
        if not sent_by:
            text = match._c2w_sms_text()
            ok = _send_sms(self.env, self.phone, text)
            self._c2w_log_event('sms', 'outbound', text, 'sent' if ok else 'failed')
            if not ok:
                match.sudo().write({'notify_state': 'failed'})
                return False
            sent_by = 'sms'
        match.sudo().write({'notify_state': 'sent', 'notified_at': fields.Datetime.now(), 'notify_channel': sent_by})
        self.sudo().job_alert_at = fields.Datetime.now()
        return True

    def _c2w_job_alert_whatsapp(self, match, parts):
        """Meta's answer, or None when there's no way to send (window shut, template not approved)."""
        Message = self.env['whatsapp.message'].sudo()
        ids = (GOOD + str(match.id), BAD + str(match.id), STOP)
        if self._c2w_wa_window_open():
            return Message.send_whatsapp_payload(self.phone, {
                'type': 'interactive',
                'interactive': {
                    'type': 'button',
                    'body': {'text': WA_BODY.format(**parts)},
                    'footer': {'text': FOOTER},
                    'action': {'buttons': [
                        {'type': 'reply', 'reply': {'id': ids[0], 'title': '👍 Good match'}},
                        {'type': 'reply', 'reply': {'id': ids[1], 'title': '👎 Not for me'}},
                        {'type': 'reply', 'reply': {'id': ids[2], 'title': 'Stop job alerts'}},
                    ]},
                },
            }, log_body=WA_BODY.format(**parts), log_type='interactive')
        template = self.env['whatsapp.template'].sudo().search(
            [('name', '=', ALERT_TEMPLATE), ('status', '=', 'APPROVED')], limit=1)
        if not template:
            return None
        order = ('name', 'title', 'employer', 'location', 'closing', 'link')
        return Message.send_whatsapp_payload(self.phone, {
            'type': 'template',
            'template': {
                'name': template.name,
                'language': {'code': template.language},
                'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': parts[k]} for k in order]}] + [
                    {'type': 'button', 'sub_type': 'quick_reply', 'index': str(i),
                     'parameters': [{'type': 'payload', 'payload': payload}]} for i, payload in enumerate(ids)],
            },
        }, account=template.account_id or None, log_body=WA_BODY.format(**parts), log_type='template')

    def _c2w_set_job_alerts(self, stop, channel):
        self.ensure_one()
        if self.job_alerts_stopped != stop:
            self.sudo().job_alerts_stopped = stop
            self._c2w_log_event(channel, 'inbound', 'Job alerts: %s' % ('stopped' if stop else 'started again'))


class Chat2workWaSessionJobAlert(models.Model):
    _inherit = 'chat2work.wa.session'

    @api.model
    def wa_handle(self, webhook_message, value_data):
        inp, is_text = self._reply_input(webhook_message)
        word = inp.strip().lower()
        if inp.startswith('c2w:jf:') or (is_text and word in ('stop', 'start')):
            phone_number_id = ((value_data or {}).get('metadata') or {}).get('phone_number_id')
            account = self.env['comm.whatsapp.account'].sudo().find_for_phone_number_id(phone_number_id)
            wa_id = re.sub(r'\D', '', webhook_message.get('from') or '')
            candidate = self.env['chat2work.candidate'].sudo().search(
                [('phone', 'in', msisdn_variants(normalize_msisdn(wa_id)))], limit=1)
            if self._account_allowed(account) and candidate and (inp.startswith('c2w:jf:') or word == 'start'
                                                                 or not self.sudo().search_count([('wa_id', '=', wa_id)])):
                self.sudo()._c2w_feedback_reply(wa_id, account, candidate, inp, word)
                return True
        return super().wa_handle(webhook_message, value_data)

    @api.model
    def _c2w_feedback_reply(self, wa_id, account, candidate, inp, word):
        if inp == STOP or word == 'stop':
            candidate._c2w_set_job_alerts(True, 'whatsapp')
            self._c2w_text(wa_id, account, STOPPED)
            return
        if word == 'start':
            candidate._c2w_set_job_alerts(False, 'whatsapp')
            self._c2w_text(wa_id, account, STARTED)
            return
        verdict = 'good' if inp.startswith(GOOD) else 'bad'
        match_id = inp.rsplit(':', 1)[-1]
        match = self.env['chat2work.listing.match'].sudo().browse(int(match_id)).exists() \
            if match_id.isdigit() else self.env['chat2work.listing.match']
        if not match or match.candidate_id != candidate:
            self._c2w_text(wa_id, account, "Sorry, we couldn't find that job.")
            return
        match._c2w_record_feedback(verdict, 'whatsapp')
        self._c2w_text(wa_id, account, THANKS_GOOD if verdict == 'good' else THANKS_BAD)


class Chat2workSmsReplies(models.Model):
    _inherit = 'whatsapp.chatbot.message'

    @api.model
    def process_incoming_sms_message(self, from_number, message_text, sms_message_id=None, to_number=None):
        """1 / 2 after an SMS job alert, STOP and START. Anything else goes to the chatbot."""
        word = (message_text or '').strip().lower().rstrip('.!')
        if word in ('1', '2', 'stop', 'start'):
            candidate = self.env['chat2work.candidate'].sudo().search(
                [('phone', 'in', msisdn_variants(normalize_msisdn(from_number or '')))], limit=1)
            if candidate and self._c2w_sms_job_reply(candidate, word):
                return True
        return super().process_incoming_sms_message(from_number, message_text, sms_message_id=sms_message_id,
                                                    to_number=to_number)

    @api.model
    def _c2w_sms_job_reply(self, candidate, word):
        if word in ('stop', 'start'):
            candidate._c2w_set_job_alerts(word == 'stop', 'sms')
            reply = 'Chat2Work: %s' % _plain(STOPPED if word == 'stop' else STARTED)
        else:
            since = fields.Datetime.now() - timedelta(days=SMS_REPLY_DAYS)
            match = candidate.listing_match_ids.sudo().filtered(
                lambda m: m.notify_channel == 'sms' and m.notified_at and m.notified_at >= since
                and not m.feedback).sorted('notified_at', reverse=True)[:1]
            if not match:
                return False
            match._c2w_record_feedback('good' if word == '1' else 'bad', 'sms')
            reply = 'Chat2Work: %s' % _plain(THANKS_GOOD if word == '1' else THANKS_BAD)
        _send_sms(self.env, candidate.phone, reply)
        return True
