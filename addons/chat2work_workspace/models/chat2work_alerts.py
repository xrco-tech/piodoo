# -*- coding: utf-8 -*-
"""Who is waiting for an agent, and telling agents about it.

Three kinds of waiting: a candidate whose last WhatsApp or SMS is unanswered, a
callback nobody has picked up, and someone who wrote in on WhatsApp without
being a candidate (they never finished sign-up, or never started it).

The screen asks `ws_alerts` for the list and raises an alert for whatever is
new on it. A cron emails chosen people about anyone left waiting too long, for
when nobody has Odoo open.
"""

import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .chat2work_live import _notify
from .chat2work_workspace import OPEN_CALLBACK, REPLY_CHANNELS, _dt
from .chat2work_workspace_ai import _ai_first_name

_logger = logging.getLogger(__name__)

# How far back a number that isn't a candidate is still listed.
UNKNOWN_DAYS = 14
# Only something that started waiting this recently raises an alert on screen.
ALERT_HOURS = 24
ALERT_LIMIT = 40
THREAD_LIMIT = 200
WINDOW_HOURS = 24  # WhatsApp lets a business answer freely this long after their last message
EMAIL_MINUTES_PARAM = 'chat2work_workspace.waiting_email_minutes'
EMAIL_LAST_PARAM = 'chat2work_workspace.waiting_email_last'
EMAIL_MINUTES = 15
EMAIL_GROUP = 'chat2work_workspace.group_waiting_email'
CRON_MINUTES = 5


class Chat2workWorkspaceHandled(models.Model):
    """An agent's "dealt with" on a number that isn't a candidate. A newer message
    from the same number puts it back on the list."""
    _name = 'chat2work.workspace.handled'
    _description = 'Chat2Work: number dealt with'
    _rec_name = 'wa_id'

    wa_id = fields.Char('WhatsApp number', required=True, index=True)
    handled_at = fields.Datetime('Dealt with', required=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', 'By', default=lambda self: self.env.user)

    _sql_constraints = [('wa_id_unique', 'unique(wa_id)', 'This number is already on the list.')]


class WhatsAppMessageWorkspace(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(record.is_incoming for record in records):
            _notify(self.env, 'whatsapp')
        return records


class Chat2workWorkspaceAlerts(models.AbstractModel):
    _inherit = 'chat2work.workspace'

    # ── People who aren't candidates ─────────────────────────────────────────

    def _unknown_latest(self, wa_id=None):
        """The newest WhatsApp message of each number that wrote in recently and
        is not a candidate: [{wa_id, id, at, incoming, body, name, needs_reply}],
        newest first."""
        since = fields.Datetime.now() - timedelta(days=UNKNOWN_DAYS)
        self.env['whatsapp.message'].flush_model()
        self.env['chat2work.candidate'].flush_model()
        where, params = '', [since, since]
        only = self.env['ir.config_parameter'].sudo().get_param('chat2work.wa_phone_number_id')
        if only:
            where += ' AND m.phone_number_id = %s'
            params.append(only)
        if wa_id:
            where += ' AND m.wa_id = %s'
            params.append(wa_id)
        self.env.cr.execute("""
            SELECT DISTINCT ON (m.wa_id)
                   m.wa_id, m.id, m.message_timestamp, m.is_incoming,
                   COALESCE(NULLIF(m.message_body, ''), m.caption, ''), m.message_type,
                   (SELECT x.contact_name FROM whatsapp_message x
                     WHERE x.wa_id = m.wa_id AND x.is_incoming AND x.contact_name IS NOT NULL
                     ORDER BY x.message_timestamp DESC, x.id DESC LIMIT 1)
              FROM whatsapp_message m
             WHERE m.wa_id IS NOT NULL AND m.wa_id != ''
               AND m.message_timestamp >= %s
               AND COALESCE(m.message_type, '') != 'reaction'
               AND EXISTS (SELECT 1 FROM whatsapp_message x
                            WHERE x.wa_id = m.wa_id AND x.is_incoming AND x.message_timestamp >= %s)
               AND NOT EXISTS (SELECT 1 FROM chat2work_candidate c
                                WHERE regexp_replace(COALESCE(c.phone, ''), '[^0-9]', '', 'g') = m.wa_id)
               """ + where + """
             ORDER BY m.wa_id, m.message_timestamp DESC, m.id DESC
        """, params)
        rows = self.env.cr.fetchall()
        handled = {h.wa_id: h.handled_at for h in self.env['chat2work.workspace.handled'].sudo().search(
            [('wa_id', 'in', [row[0] for row in rows])])}
        result = []
        for number, message_id, at, incoming, body, message_type, name in rows:
            done = handled.get(number)
            result.append({
                'wa_id': number, 'id': message_id, 'at': at, 'incoming': bool(incoming),
                'body': (body or '').strip() or '[%s]' % (message_type or 'message'),
                'name': self._unknown_name(number, name),
                'needs_reply': bool(incoming) and not (done and done >= at),
            })
        result.sort(key=lambda r: r['at'], reverse=True)
        return result

    @api.model
    def _unknown_name(self, wa_id, profile_name):
        """Their WhatsApp profile name, or the number when they have none."""
        name = (profile_name or '').strip()
        return name if name and name.lstrip('+').replace(' ', '') != wa_id else '+%s' % wa_id

    @api.model
    def ws_unknown(self, search='', offset=0, limit=None):
        self._check_agent()
        offset, limit = self._page(offset, limit)
        term = (search or '').strip().lower()
        rows = [{
            'id': row['wa_id'],
            'name': row['name'],
            'phone': '+%s' % row['wa_id'],
            'channel': 'whatsapp',
            'needs_reply': row['needs_reply'],
            'preview': row['body'][:140],
            'preview_out': not row['incoming'],
            'at': _dt(row['at']),
        } for row in self._unknown_latest()]
        if term:
            rows = [r for r in rows if term in r['name'].lower() or term.lstrip('+0') in r['phone']]
        return rows[offset:offset + limit]

    @api.model
    def ws_unknown_thread(self, wa_id):
        self._check_agent()
        latest = self._unknown_latest(wa_id)
        if not latest:
            return False
        latest = latest[0]
        messages = self.env['whatsapp.message'].sudo().search(
            [('wa_id', '=', wa_id), ('message_type', '!=', 'reaction')],
            order='message_timestamp desc, id desc', limit=THREAD_LIMIT)
        incoming = messages.filtered('is_incoming')
        window = fields.Datetime.now() - timedelta(hours=WINDOW_HOURS)
        return {
            'id': wa_id,
            'name': latest['name'],
            'phone': '+%s' % wa_id,
            'needs_reply': latest['needs_reply'],
            'window_open': bool(incoming) and incoming[0].message_timestamp >= window,
            'first_at': _dt(messages[-1].message_timestamp),
            'received': len(incoming),
            'timeline': [{
                'id': m.id,
                'dir': 'inbound' if m.is_incoming else 'outbound',
                'channel': 'whatsapp',
                'channel_name': 'WhatsApp',
                'body': (m.message_body or m.caption or '').strip() or '[%s]' % (m.message_type or 'message'),
                'at': _dt(m.message_timestamp),
                'status': m.message_status or '',
                'fail_reason': m.failure_reason or '',
            } for m in reversed(messages)],
        }

    @api.model
    def ws_unknown_send(self, wa_id, text):
        """Answer someone who isn't a candidate. WhatsApp only takes a typed
        message within 24 hours of their last one."""
        self._check_agent()
        thread = self.ws_unknown_thread(wa_id)
        text = (text or '').strip()
        if not thread or not text:
            return thread
        if not thread['window_open']:
            raise UserError(_("Their last message was more than 24 hours ago, so WhatsApp won't deliver a typed reply."))
        Message = self.env['whatsapp.message'].sudo()
        last = Message.search([('wa_id', '=', wa_id), ('is_incoming', '=', True)],
                              order='message_timestamp desc, id desc', limit=1)
        account = self.env['comm.whatsapp.account'].sudo().find_for_phone_number_id(last.phone_number_id)
        result = Message.send_whatsapp_payload(
            wa_id, {'type': 'text', 'text': {'body': text}}, account=account or None,
            log_body=text, log_type='text')
        if not result.get('success'):
            raise UserError(_("WhatsApp didn't take the message: %s", result.get('error') or _("no reason given")))
        _notify(self.env, 'whatsapp')
        return self.ws_unknown_thread(wa_id)

    @api.model
    def ws_unknown_done(self, wa_id):
        """Take a number off the waiting list until they write again."""
        self._check_agent()
        Handled = self.env['chat2work.workspace.handled'].sudo()
        vals = {'handled_at': fields.Datetime.now(), 'user_id': self.env.uid}
        record = Handled.search([('wa_id', '=', wa_id)], limit=1)
        if record:
            record.write(vals)
        else:
            Handled.create(dict(vals, wa_id=wa_id))
        _notify(self.env, 'whatsapp')
        return True

    # ── Who is waiting ───────────────────────────────────────────────────────

    def _waiting_replies(self):
        """Candidates whose newest WhatsApp or SMS came from them:
        [(candidate id, interaction id, at, channel code)]."""
        self.env['comm.interaction'].flush_model()
        self.env['comm.conversation'].flush_model()
        self.env.cr.execute("""
            SELECT candidate_id, id, at, code FROM (
                SELECT DISTINCT ON (c.partner_id) cand.id AS candidate_id, i.id, i.at, i.direction, ch.code
                  FROM comm_interaction i
                  JOIN comm_conversation c ON c.id = i.conversation_id
                  JOIN comm_channel ch ON ch.id = i.channel_id
                  JOIN chat2work_candidate cand ON cand.partner_id = c.partner_id AND cand.active
                 WHERE ch.code IN %s
                 ORDER BY c.partner_id, i.at DESC, i.id DESC) latest
             WHERE direction = 'inbound'
        """, [REPLY_CHANNELS])
        return self.env.cr.fetchall()

    def _waiting_items(self):
        """Everyone waiting for an agent, longest wait last:
        [{key, kind, name, text, candidate_id, wa_id, since}]. The key changes
        when they write again, so a second message is a new alert."""
        Candidate = self.env['chat2work.candidate'].sudo()
        items = []
        replies = self._waiting_replies()
        names = {c.id: c.display_name for c in Candidate.browse([row[0] for row in replies])}
        for candidate_id, interaction_id, at, code in replies:
            items.append({
                'key': 'reply:%s:%s' % (candidate_id, interaction_id), 'kind': 'reply',
                'name': names.get(candidate_id) or _("A candidate"),
                'text': _("Sent an SMS") if code == 'sms' else _("Sent a WhatsApp message"),
                'candidate_id': candidate_id, 'wa_id': False, 'since': at,
            })
        callbacks = self.env['chat2work.callback.request'].sudo().search(
            [('state', '=', 'new'), ('candidate_id', '!=', False)])
        for callback in callbacks:
            items.append({
                'key': 'callback:%s' % callback.id, 'kind': 'callback',
                'name': callback.candidate_id.display_name,
                'text': _("Asked for a callback"),
                'candidate_id': callback.candidate_id.id, 'wa_id': False, 'since': callback.create_date,
            })
        for row in self._unknown_latest():
            if row['needs_reply']:
                items.append({
                    'key': 'unknown:%s:%s' % (row['wa_id'], row['id']), 'kind': 'unknown',
                    'name': row['name'],
                    'text': _("Wrote in on WhatsApp. Not a candidate yet."),
                    'candidate_id': False, 'wa_id': row['wa_id'], 'since': row['at'],
                })
        items.sort(key=lambda item: item['since'], reverse=True)
        return items

    @api.model
    def ws_counts(self):
        counts = super().ws_counts()
        counts['unknown'] = sum(1 for row in self._unknown_latest() if row['needs_reply'])
        return counts

    @api.model
    def ws_alerts(self):
        """What the alert icon shows: how many are waiting, and those who started
        waiting in the last day (the screen alerts on the ones it hasn't seen)."""
        self._check_agent()
        items = self._waiting_items()
        recent = fields.Datetime.now() - timedelta(hours=ALERT_HOURS)
        counts = {
            'reply': sum(1 for item in items if item['kind'] == 'reply'),
            'callback': self.env['chat2work.callback.request'].search_count(
                [('state', 'in', OPEN_CALLBACK), ('candidate_id', '!=', False)]),
            'unknown': sum(1 for item in items if item['kind'] == 'unknown'),
        }
        return {
            'counts': counts,
            'count': sum(counts.values()),
            'items': [dict(item, since=_dt(item['since']))
                      for item in items if item['since'] >= recent][:ALERT_LIMIT],
        }

    # ── Email about people left waiting ──────────────────────────────────────

    @api.model
    def _waiting_email_minutes(self):
        value = self.env['ir.config_parameter'].sudo().get_param(EMAIL_MINUTES_PARAM)
        try:
            return int(value) if value not in (None, False, '') else EMAIL_MINUTES
        except ValueError:
            return EMAIL_MINUTES

    @api.model
    def _cron_waiting_email(self):
        """Email the chosen people about anyone who has now waited too long. Each
        wait is emailed once: when it crosses the limit between two runs."""
        self = self.sudo()
        Param = self.env['ir.config_parameter']
        now = fields.Datetime.now()
        last = Param.get_param(EMAIL_LAST_PARAM)
        last = fields.Datetime.to_datetime(last) if last else now - timedelta(minutes=CRON_MINUTES)
        Param.set_param(EMAIL_LAST_PARAM, fields.Datetime.to_string(now))
        minutes = self._waiting_email_minutes()
        group = self.env.ref(EMAIL_GROUP, raise_if_not_found=False)
        users = group.users.filtered(lambda u: u.active and u.email) if group else self.env['res.users']
        if minutes <= 0 or not users:
            return False
        limit = timedelta(minutes=minutes)
        items = self._waiting_items()
        due = [item for item in items if last - limit < item['since'] <= now - limit]
        if not due:
            return False
        mail = self.env['mail.mail'].create(self._waiting_email_values(due, items, minutes, users))
        _logger.info("chat2work_workspace: waiting email %s queued for %s people about %s waits",
                     mail.id, len(users), len(due))
        return mail

    def _waiting_email_values(self, due, items, minutes, users):
        tz = users[0].tz or 'Africa/Johannesburg'
        lines = Markup()
        for item in due:
            when = fields.Datetime.context_timestamp(self.with_context(tz=tz), item['since']).strftime('%H:%M')
            lines += Markup("<li><b>%s</b>: %s, since %s</li>") % (self._waiting_email_name(item), item['text'], when)
        count = lambda kind: sum(1 for item in items if item['kind'] == kind)  # noqa: E731
        url = '%s/odoo/action-chat2work_workspace.action_chat2work_workspace' % self.get_base_url()
        body = Markup(
            "<p>%s</p><ul>%s</ul><p>%s</p><p><a href=\"%s\">%s</a></p>"
        ) % (
            _("Nobody has answered these for more than %s minutes:", minutes),
            lines,
            _("Waiting altogether: %(reply)s for a reply, %(callback)s for a callback, %(unknown)s not yet candidates.",
              reply=count('reply'), callback=count('callback'), unknown=count('unknown')),
            url, _("Open the Workspace"),
        )
        company = self.env.company
        return {
            'subject': _("Chat2Work: %s waiting for an answer", len(due)),
            'body_html': body,
            'email_from': company.email_formatted or self.env.ref('base.partner_root').email_formatted,
            'email_to': ','.join(users.mapped('email_formatted')),
            'auto_delete': True,
        }

    @api.model
    def _waiting_email_name(self, item):
        """A first name only: an email leaves Odoo, so no phone numbers in it."""
        if item['kind'] == 'unknown':
            return escape(_("Someone who isn't a candidate yet (number ending %s)", item['wa_id'][-4:]))
        return escape(_ai_first_name(item['name']) or _("A candidate"))
