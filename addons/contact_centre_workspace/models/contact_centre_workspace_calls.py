# -*- coding: utf-8 -*-
"""What the Calls section of the workspace reads: WhatsApp calls and VoIP
calls in one list, newest first, and one call with its recording, transcript
and outcome.

Calls are read as the signed-in agent, so whatever record rules limit which
calls they may see apply here too."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .contact_centre_workspace import COLOURS

# line -> (model, direction field, status field, time field)
LINES = {
    'wa': ('whatsapp.call.log', 'call_direction', 'call_status', 'call_timestamp'),
    'voip': ('comm.voip.call', 'direction', 'state', 'start_time'),
}
VOIP_UNANSWERED = ('no_answer', 'busy', 'failed', 'cancelled')
SENTIMENTS = ('positive', 'neutral', 'negative')


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _call_domain(self, line, pill, term):
        """The calls of one line that match the filter, or None when the
        filter leaves that line out altogether."""
        _model, direction, status, _at = LINES[line]
        domain = []
        if pill == 'missed':
            domain += ([('is_missed', '=', True)] if line == 'wa'
                       else [(direction, '=', 'incoming'), (status, 'in', VOIP_UNANSWERED)])
        elif pill in ('incoming', 'outgoing'):
            domain.append((direction, '=', pill))
        elif pill in ('whatsapp', 'voip'):
            if (pill == 'whatsapp') != (line == 'wa'):
                return None
        elif pill == 'no_outcome':
            # Only WhatsApp calls carry an outcome.
            if line != 'wa':
                return None
            domain += [('disposition_id', '=', False), ('is_missed', '=', False),
                       ('call_status', 'in', ('answered', 'ended'))]
        term = (term or '').strip()
        if term:
            digits = ''.join(ch for ch in term if ch.isdigit())
            number = digits[-9:] if len(digits) >= 3 else term
            domain += ['|', '|', ('partner_id.name', 'ilike', term),
                       ('from_number', 'ilike', number), ('to_number', 'ilike', number)]
        return domain

    @api.model
    def _call_duration(self, seconds):
        seconds = int(seconds or 0)
        if seconds <= 0:
            return ''
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return '%d:%02d:%02d' % (hours, minutes, seconds) if hours else '%d:%02d' % (minutes, seconds)

    @api.model
    def _call_outcome(self, line, call):
        """(kind, words): kind is missed | answered | unanswered | live."""
        if line == 'wa':
            status = call.call_status
            if call.is_missed:
                return 'missed', _("Missed")
            if status == 'answered' or (status == 'ended' and call.duration):
                return 'answered', _("Answered")
            if status == 'declined':
                return 'unanswered', _("Declined")
            if status == 'failed':
                return 'unanswered', _("Failed")
            if status == 'ended':
                return 'unanswered', _("No answer")
            return 'live', _("Ringing")
        state = call.state
        if state == 'completed':
            return 'answered', _("Answered")
        if state in VOIP_UNANSWERED:
            words = {'no_answer': _("No answer"), 'busy': _("Busy"), 'failed': _("Failed"), 'cancelled': _("Cancelled")}
            return ('missed', _("Missed")) if call.direction == 'incoming' else ('unanswered', words[state])
        return 'live', {'in_progress': _("In progress"), 'queued': _("Queued")}.get(state, _("Ringing"))

    @api.model
    def _call_row(self, line, call):
        _model, direction, _status, at = LINES[line]
        incoming = call[direction] == 'incoming'
        number = (call.from_number if incoming else call.to_number) or ''
        name = call.partner_id.name or number or _("Unknown")
        kind, words = self._call_outcome(line, call)
        return {
            'key': '%s-%s' % (line, call.id),
            'line': 'whatsapp' if line == 'wa' else 'voip',
            'name': name,
            'number': number,
            'partner_id': call.partner_id.id,
            'incoming': incoming,
            'kind': kind,
            'status': words,
            'at': fields.Datetime.to_string(call[at] or call.create_date),
            'duration': self._call_duration(call.duration),
            'recorded': bool(call.recording_ids) if 'recording_ids' in call._fields else False,
            'disposition': call.disposition_id.name or '' if line == 'wa' else '',
            'initials': self._initials(call.partner_id.name),
            'colour': COLOURS[(call.partner_id.id or call.id) % len(COLOURS)],
        }

    @api.model
    def _call(self, key):
        line, _sep, call_id = (key or '').partition('-')
        if line not in LINES or not call_id.isdigit():
            raise UserError(_("This call no longer exists."))
        call = self.env[LINES[line][0]].search([('id', '=', int(call_id))], limit=1)
        if not call:
            raise UserError(_("This call no longer exists."))
        return line, call

    @api.model
    def _calls(self, pill='all', search='', limit=40, extra=None):
        """Matching calls of both lines as rows, newest first, at most `limit`."""
        rows = []
        for line, (model, _direction, _status, at) in LINES.items():
            if model not in self.env:
                continue
            domain = self._call_domain(line, pill, search)
            if domain is None:
                continue
            if extra:
                domain = domain + extra[line]
            calls = self.env[model].search(domain, order='%s desc nulls last, id desc' % at, limit=limit)
            rows += [self._call_row(line, call) for call in calls]
        rows.sort(key=lambda row: (row['at'], row['key']), reverse=True)
        return rows[:limit]

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_calls(self, pill='all', search='', offset=0, limit=40):
        self._agent()
        offset, limit = int(offset), int(limit)
        rows = self._calls(pill, search, limit=offset + limit + 1)
        return {'rows': rows[offset:offset + limit], 'more': len(rows) > offset + limit}

    # ── One call ─────────────────────────────────────────────────────────
    @api.model
    def ws_call(self, key):
        self._agent()
        line, call = self._call(key)
        row = self._call_row(line, call)
        _model, _direction, _status, at = LINES[line]

        recordings = []
        if 'recording_ids' in call._fields:
            route = '/whatsapp/call/recording/%s' if line == 'wa' else '/voip/call/recording/%s'
            recordings = [{'id': att.id, 'url': route % att.id, 'duration': att.recording_duration_display or ''}
                          for att in call.recording_ids]

        # The same call in the Contact Centre thread leads to the conversation.
        link = 'whatsapp_call_log_id' if line == 'wa' else 'comm_voip_call_id'
        message = self.env['contact.centre.message'].sudo().search([(link, '=', call.id)], limit=1)
        contact = message.contact_id
        if not contact and call.partner_id:
            contact = self.env['contact.centre.contact'].sudo().search([('partner_id', '=', call.partner_id.id)], limit=1)

        # Other calls with the same person, on either line.
        number = ''.join(ch for ch in row['number'] if ch.isdigit())[-9:]
        who = []
        if call.partner_id:
            who = [('partner_id', '=', call.partner_id.id)]
        elif len(number) >= 7:
            who = ['|', ('from_number', 'ilike', number), ('to_number', 'ilike', number)]
        history = []
        if who:
            extra = {name: who + ([('id', '!=', call.id)] if name == line else []) for name in LINES}
            history = self._calls(limit=8, extra=extra)

        transcribes = 'transcript' in call._fields
        if line == 'wa':
            account = call.account_id.display_name if 'account_id' in call._fields and call.account_id else ''
            end = call.end_timestamp
            transferred = call.transferred_from_user_id.name or ''
        else:
            account = call.account_id.display_name or ''
            end = call.end_time
            transferred = ''
        details = [
            {'label': _("Line"), 'value': 'WhatsApp' if line == 'wa' else 'VoIP'},
            {'label': _("Number used"), 'value': account},
            {'label': _("Agent"), 'value': call.agent_user_id.name or ''},
            {'label': _("Transferred by"), 'value': transferred},
            {'label': _("From"), 'value': call.from_number or ''},
            {'label': _("To"), 'value': call.to_number or ''},
            {'label': _("Started"), 'value': fields.Datetime.to_string(call[at]) if call[at] else '', 'time': True},
            {'label': _("Ended"), 'value': fields.Datetime.to_string(end) if end else '', 'time': True},
        ]
        row.update({
            'recordings': recordings,
            'transcript': (call.transcript or '') if transcribes else '',
            'transcript_state': (call.transcript_state or 'none') if transcribes else 'none',
            'can_transcribe': transcribes and bool(recordings),
            'ai': {
                'summary': call.ai_summary or '',
                'sentiment': call.ai_sentiment if call.ai_sentiment in SENTIMENTS else '',
                'suggested': call.ai_suggested_disposition or '',
            } if transcribes else False,
            'has_outcome': line == 'wa',
            'disposition_id': call.disposition_id.id if line == 'wa' else False,
            'note': (call.disposition_note if line == 'wa' else call.notes) or '',
            'contact_id': contact.id,
            'history': history,
            'details': details,
        })
        return row

    @api.model
    def ws_call_outcome(self, key, disposition_id=False, note=''):
        """Save the wrap-up of a call. VoIP calls keep a note only."""
        self._agent()
        line, call = self._call(key)
        if line == 'wa':
            call.action_set_disposition(int(disposition_id or 0) or False, note or '')
        else:
            call.write({'notes': note or False})
        return True

    @api.model
    def ws_call_transcribe(self, key):
        """Transcribe the recording now, as the button on the call's form does."""
        self._agent()
        _line, call = self._call(key)
        if 'transcript' not in call._fields:
            return False
        call.action_transcribe()
        return self.ws_call(key)
