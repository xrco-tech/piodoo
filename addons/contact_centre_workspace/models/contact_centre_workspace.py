# -*- coding: utf-8 -*-
"""What the Contact Centre workspace screen reads: one call per pane.

Nothing here sends anything. Replies, templates and wrap-up go through the
Contact Centre Inbox's own methods on contact.centre.contact."""

from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

AGENT = 'contact_centre.group_contact_centre_agent'
STATES = ('open', 'pending', 'resolved')
CHANNELS = ('whatsapp', 'sms', 'voice', 'email')
LONG_AGO = datetime(1970, 1, 1)
COLOURS = ['#b5651d', '#2f6f8f', '#7a4fa3', '#8a5a44', '#2e7d5b', '#a3466b', '#3f7f6a', '#5a6fb0']
# Rail entries after Inbox: (key, label, icon, the screen that exists today).
RAIL = [
    ('calls', 'Calls', 'fa-phone', 'comm_whatsapp_calling.action_whatsapp_call_log'),
    ('contacts', 'Contacts', 'fa-address-book-o', 'contact_centre.action_contact_centre_contact'),
    ('campaigns', 'Campaigns', 'fa-bullhorn', 'contact_centre.action_contact_centre_campaign_overview'),
    ('templates', 'Templates', 'fa-file-text-o', 'contact_centre.action_whatsapp_template'),
    ('ai', 'AI Ops', 'fa-magic', 'contact_centre_ai_ops.action_contact_centre_ai_ops'),
]


class ContactCentreContact(models.Model):
    _inherit = 'contact.centre.contact'

    # When an agent last had this conversation open in the workspace. Shared:
    # once one agent has seen a message it stops counting as unread for all.
    ws_seen_at = fields.Datetime('Last Seen in Workspace', copy=False)


class ContactCentreWorkspace(models.AbstractModel):
    _name = 'contact.centre.workspace'
    _description = 'Contact Centre Workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    def _agent(self):
        if not self.env.user.has_group(AGENT):
            raise AccessError(_("Only Contact Centre agents can use the workspace."))

    @api.model
    def _initials(self, name):
        words = [w for w in (name or '').split() if w[:1].isalpha()]
        # Contacts made from a bare number are named "WhatsApp 2782…".
        if not words or any(ch.isdigit() for ch in (name or '')):
            return '#'
        return (words[0][:1] + (words[-1][:1] if len(words) > 1 else '')).upper()

    @api.model
    def _preview(self, text):
        text = ' '.join((text or '').split())
        return text[:90]

    def _flush(self):
        self.env['contact.centre.message'].flush_model()
        self.env['contact.centre.contact'].flush_model()
        self.env['whatsapp.message'].flush_model()

    def _wa_ids(self, contact_ids):
        """{contact id: the WhatsApp ids its messages came from}."""
        result = {}
        if not contact_ids:
            return result
        self.env.cr.execute("""
            SELECT DISTINCT m.contact_id, w.wa_id
              FROM contact_centre_message m
              JOIN whatsapp_message w ON w.id = m.whatsapp_message_id
             WHERE m.contact_id IN %s AND w.wa_id IS NOT NULL
        """, [tuple(contact_ids)])
        for contact_id, wa_id in self.env.cr.fetchall():
            result.setdefault(contact_id, set()).add(wa_id)
        return result

    def _answered_at(self, contact_ids, seen=True):
        """{contact id: when the conversation was last answered or looked at}.

        The latest of: our last message or call in the thread that went out, the last
        WhatsApp message sent to their number by anything (the bot's replies
        are not copied into the thread), and, unless `seen` is False, the last
        time an agent had the conversation open here."""
        answered = dict.fromkeys(contact_ids, LONG_AGO)
        if not contact_ids:
            return answered
        cr = self.env.cr
        cr.execute("""
            SELECT contact_id, max(message_timestamp) FROM contact_centre_message
             WHERE contact_id IN %s AND direction = 'outbound' AND COALESCE(status, '') <> 'failed'
             GROUP BY contact_id
        """, [tuple(contact_ids)])
        for contact_id, at in cr.fetchall():
            answered[contact_id] = max(answered[contact_id], at)
        if seen:
            cr.execute("SELECT id, ws_seen_at FROM contact_centre_contact WHERE id IN %s AND ws_seen_at IS NOT NULL",
                       [tuple(contact_ids)])
            for contact_id, at in cr.fetchall():
                answered[contact_id] = max(answered[contact_id], at)
        wa_ids = self._wa_ids(contact_ids)
        numbers = {wa_id for ids in wa_ids.values() for wa_id in ids}
        if numbers:
            cr.execute("""
                SELECT wa_id, max(message_timestamp) FROM whatsapp_message
                 WHERE wa_id IN %s AND is_incoming IS NOT TRUE GROUP BY wa_id
            """, [tuple(numbers)])
            sent = dict(cr.fetchall())
            for contact_id, ids in wa_ids.items():
                for wa_id in ids:
                    if sent.get(wa_id):
                        answered[contact_id] = max(answered[contact_id], sent[wa_id])
        return answered

    def _unread(self, contact_ids, seen=True):
        """{contact id: (how many messages are unanswered, when the oldest came in)}.

        Calls do not count: a call is answered or missed, not replied to.
        With `seen` False an agent having looked does not count as an answer:
        that is how long the person has really been waiting."""
        if not contact_ids:
            return {}
        self._flush()
        answered = self._answered_at(contact_ids, seen=seen)
        ids = list(answered)
        self.env.cr.execute("""
            SELECT m.contact_id, count(*), min(m.message_timestamp)
              FROM contact_centre_message m
              JOIN unnest(%s::int[], %s::timestamp[]) AS t(cid, at) ON t.cid = m.contact_id
              JOIN contact_centre_contact c ON c.id = m.contact_id
             WHERE m.direction = 'inbound' AND m.channel <> 'voice'
               AND m.message_timestamp > t.at
               AND COALESCE(c.state, 'open') <> 'resolved'
             GROUP BY m.contact_id
        """, [ids, [answered[i] for i in ids]])
        return {contact_id: (count, oldest) for contact_id, count, oldest in self.env.cr.fetchall()}

    def _last_messages(self, contact_ids):
        if not contact_ids:
            return {}
        self._flush()
        self.env.cr.execute("""
            SELECT DISTINCT ON (contact_id) contact_id, channel, direction, body_text, message_timestamp
              FROM contact_centre_message
             WHERE contact_id IN %s
             ORDER BY contact_id, message_timestamp DESC, id DESC
        """, [tuple(contact_ids)])
        return {row[0]: row[1:] for row in self.env.cr.fetchall()}

    def _contact(self, contact_id):
        contact = self.env['contact.centre.contact'].search([('id', '=', int(contact_id or 0))], limit=1)
        if not contact:
            raise UserError(_("This conversation no longer exists."))
        return contact

    # ── Opening the screen ───────────────────────────────────────────────
    @api.model
    def ws_boot(self):
        self._agent()
        rail = []
        for key, label, icon, xmlid in RAIL:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action:
                rail.append({'key': key, 'label': label, 'icon': icon, 'action': action.id})
        dispositions = self.env['comm.disposition'].sudo().search_read([], ['name'], order='sequence, name')
        user = self.env.user
        return {
            # The VoIP button shows for agents who have their own extension.
            'voip': 'dialer_sip_ext' in user._fields and bool(user.sudo().dialer_sip_ext),
            'rail': rail,
            'dispositions': dispositions,
            'counts': self.ws_counts(),
            'ai': 'ai_summary' in self.env['contact.centre.contact']._fields,
            'me': {'name': self.env.user.name, 'initials': self._initials(self.env.user.name)},
        }

    @api.model
    def ws_counts(self):
        self._agent()
        ids = self.env['contact.centre.contact'].search([('state', '!=', 'resolved')], limit=5000).ids
        return {'unread': len(self._unread(ids))}

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_list(self, pill='all', search='', offset=0, limit=40, campaign_id=False):
        self._agent()
        domain = []
        if pill in STATES:
            domain.append(('state', '=', pill))
        if campaign_id:
            domain.append(('campaign_ids', 'in', [int(campaign_id)]))
        term = (search or '').strip()
        if term:
            domain += ['|', '|', ('name', 'ilike', term), ('phone_number', 'ilike', term), ('email', 'ilike', term)]
        Contact = self.env['contact.centre.contact']
        ids = Contact.search(domain, order='last_contact_date desc nulls last, id desc', limit=2000).ids
        last = self._last_messages(ids)
        unread = self._unread(ids)
        if pill == 'unread':
            ids = [i for i in ids if i in unread]
        elif pill in CHANNELS:
            ids = [i for i in ids if last.get(i) and last[i][0] == pill]
        page = ids[int(offset):int(offset) + int(limit)]
        rows = []
        for contact in Contact.browse(page):
            channel, direction, body, at = last.get(contact.id) or (False, False, '', False)
            rows.append({
                'id': contact.id,
                'name': contact.name or contact.phone_number or _("Unknown"),
                'phone': contact.phone_number or '',
                'state': contact.state or 'open',
                'channel': channel,
                'out': direction == 'outbound',
                'preview': self._preview(body),
                'at': fields.Datetime.to_string(at) if at else False,
                'unread': unread.get(contact.id, (0, False))[0],
                'initials': self._initials(contact.name),
                'colour': COLOURS[contact.id % len(COLOURS)],
            })
        return {'rows': rows, 'total': len(ids), 'more': len(ids) > int(offset) + len(page)}

    # ── One conversation ─────────────────────────────────────────────────
    def _thread_messages(self, contact, limit=200):
        Message = self.env['contact.centre.message']
        records = Message.search([('contact_id', '=', contact.id)], order='message_timestamp desc, id desc', limit=limit)
        messages = []
        for m in records:
            messages.append({
                'key': 'm%s' % m.id,
                'id': m.id,
                'channel': m.channel,
                'call': m.channel == 'voice',
                'out': m.direction == 'outbound',
                'auto': False,
                'body': m.body_text or '',
                'at': fields.Datetime.to_string(m.message_timestamp),
                'status': m.status or '',
                'failure': m.failure_reason or '',
                'recording_url': m.call_recording_url or '',
                'recording_duration': m.call_recording_duration or '',
                'transcript': m.voice_transcript or '',
                'wa_message_id': m.whatsapp_message_id.id,
                'disposition': m.call_disposition_id.name or '',
                'disposition_note': m.call_disposition_note or '',
            })
        # WhatsApp messages sent to this person by the bot (or anything else
        # that did not go through the inbox) are not copied into the thread.
        wa_ids = self._wa_ids(contact.ids).get(contact.id)
        if wa_ids:
            known = set(records.mapped('provider_message_id')) | set(records.whatsapp_message_id.mapped('message_id'))
            sent = self.env['whatsapp.message'].sudo().search(
                [('wa_id', 'in', list(wa_ids)), ('is_incoming', '=', False)],
                order='message_timestamp desc, id desc', limit=limit)
            for w in sent:
                if w.message_id in known:
                    continue
                messages.append({
                    'key': 'w%s' % w.id, 'id': False, 'channel': 'whatsapp', 'call': False, 'out': True,
                    'auto': True, 'body': w.message_body or _("[%s]", w.message_type or 'message'),
                    'at': fields.Datetime.to_string(w.message_timestamp),
                    'status': w.status or '', 'failure': '', 'recording_url': '', 'recording_duration': '',
                    'transcript': '', 'wa_message_id': False, 'disposition': '', 'disposition_note': '',
                })
        messages.sort(key=lambda m: (m['at'], m['key']))
        return messages[-limit:]

    def _ai(self, contact):
        if 'ai_summary' not in contact._fields:
            return False
        return {
            'summary': contact.ai_summary or '',
            'sentiment': contact.ai_sentiment or '',
            'reply': contact.ai_suggested_reply or '',
            'analysed': fields.Datetime.to_string(contact.ai_analyzed_date) if contact.ai_analyzed_date else False,
        }

    @api.model
    def ws_thread(self, contact_id, seen=True):
        self._agent()
        contact = self._contact(contact_id)
        self._flush()
        count, oldest = self._unread(contact.ids, seen=False).get(contact.id, (0, False))
        messages = self._thread_messages(contact)
        now = fields.Datetime.now()
        inbound_wa = [m['at'] for m in messages if m['channel'] == 'whatsapp' and not m['out']]
        window_open = bool(inbound_wa) and fields.Datetime.to_datetime(inbound_wa[-1]) > now - timedelta(hours=24)
        sendable = [m['channel'] for m in messages if m['channel'] in ('whatsapp', 'sms')]
        if seen:
            contact.sudo().write({'ws_seen_at': now})
        return {
            'id': contact.id,
            'name': contact.name or contact.phone_number or _("Unknown"),
            'phone': contact.phone_number or '',
            'email': contact.email or '',
            'partner_id': contact.partner_id.id,
            'has_whatsapp': bool(contact.phone_number or contact.bsuid),
            'state': contact.state or 'open',
            'initials': self._initials(contact.name),
            'colour': COLOURS[contact.id % len(COLOURS)],
            'messages': messages,
            'waiting': count,
            'waiting_since': fields.Datetime.to_string(oldest) if oldest else False,
            'window_open': window_open,
            'channel': sendable[-1] if sendable else 'whatsapp',
            'disposition_id': contact.disposition_id.id,
            'disposition_note': contact.disposition_note or '',
            'ai': self._ai(contact),
            'details': [
                {'label': _("Campaigns"), 'value': ', '.join(contact.campaign_ids.mapped('name'))},
                {'label': _("Tags"), 'value': ', '.join(contact.tag_ids.mapped('name'))},
                {'label': _("Channels"), 'value': ', '.join(sorted({self._channel_label(m['channel']) for m in messages}))},
                {'label': _("Email"), 'value': contact.email or ''},
                {'label': _("First contact"), 'value': self._date(messages[0]['at']) if messages else ''},
            ],
        }

    @api.model
    def _date(self, value):
        return fields.Datetime.to_datetime(value).strftime('%d %b %Y').lstrip('0')

    @api.model
    def _channel_label(self, channel):
        return {'whatsapp': 'WhatsApp', 'sms': 'SMS', 'voice': _("Voice"), 'email': _("Email")}.get(channel, channel or '')

    @api.model
    def ws_set_state(self, contact_id, state):
        self._agent()
        if state not in STATES:
            raise UserError(_("Unknown status."))
        self._contact(contact_id).write({'state': state})
        return True

    @api.model
    def ws_ai_refresh(self, contact_id):
        """Run the copilot on this conversation now (one AI call), as its form button does."""
        self._agent()
        contact = self._contact(contact_id)
        if not hasattr(contact, 'action_regenerate_ai_copilot'):
            return False
        contact.action_regenerate_ai_copilot()
        return self._ai(contact)
