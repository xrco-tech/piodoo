# -*- coding: utf-8 -*-
"""What Contact Centre agents do, noted for the Team report (comm_agent_activity).

A line is written when an agent answers or messages someone, marks a
conversation resolved, or says how a queued call went. Calls and their talk
time are read from the call records when the report is opened."""
from datetime import timedelta

from odoo import api, fields, models

from .contact_centre_workspace import AGENT
from .contact_centre_workspace_calls import LINES

SOURCE = 'contact_centre'


class ContactCentreContact(models.Model):
    _inherit = 'contact.centre.contact'

    def _activity_waiting(self):
        """Seconds since the oldest message of theirs that nothing has answered yet, or None."""
        self.ensure_one()
        rows = self.env['contact.centre.message'].sudo().search_read(
            [('contact_id', '=', self.id), ('channel', '!=', 'voice'), ('status', '!=', 'failed')],
            ['direction', 'message_timestamp'], order='message_timestamp desc, id desc', limit=50)
        oldest = None
        for row in rows:
            if row['direction'] != 'inbound':
                break
            oldest = row['message_timestamp']
        return (fields.Datetime.now() - oldest).total_seconds() if oldest else None

    def _activity_sent(self, wait, label):
        self.env['comm.agent.activity']._log(
            'reply' if wait else 'outreach', SOURCE, self, name=self.display_name, wait=wait, label=label)

    def action_send_reply(self, channel, body):
        wait = self._activity_waiting() if body and len(self) == 1 else None
        res = super().action_send_reply(channel, body)
        if res:
            self._activity_sent(wait, 'WhatsApp' if channel == 'whatsapp' else 'SMS')
        return res

    def action_send_template(self, template_id):
        wait = self._activity_waiting() if len(self) == 1 else None
        res = super().action_send_template(template_id)
        if isinstance(res, dict) and res.get('success'):
            self._activity_sent(wait, self.env._("Template"))
        return res


class ContactCentreWorkspaceActivity(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    @api.model
    def ws_set_state(self, contact_id, state):
        contact = self.env['contact.centre.contact'].browse(int(contact_id or 0)).exists()
        was = contact.state if contact else False
        res = super().ws_set_state(contact_id, state)
        if state == 'resolved' and was != 'resolved':
            self.env['comm.agent.activity']._log(
                'close', SOURCE, contact, name=contact.display_name, label=self.env._("Resolved"))
        return res

    @api.model
    def ws_queue_outcome(self, item_id, outcome, note='', when=False, user_id=False):
        res = super().ws_queue_outcome(item_id, outcome, note=note, when=when, user_id=user_id)
        labels = {
            'done': self.env._("Spoke to them"), 'no_answer': self.env._("No answer"),
            'later': self.env._("To call back later"), 'hand': self.env._("Handed over"),
            'dnc': self.env._("Asked not to be called"),
        }
        item = self.env['contact.centre.queue.item'].sudo().browse(int(item_id or 0)).exists()
        self.env['comm.agent.activity']._log(
            'queue_call', SOURCE, item, name=item.display_name if item else '', result=outcome,
            label=labels.get(outcome, outcome), has_note=bool((note or '').strip()))
        return res


class CommAgentActivityReport(models.AbstractModel):
    _inherit = 'comm.agent.activity.report'

    @api.model
    def _sources(self):
        return super()._sources() + [(SOURCE, 'Contact Centre')]

    @api.model
    def _agents(self, source):
        users = super()._agents(source)
        if source in (SOURCE, 'both'):
            group = self.env.ref(AGENT, raise_if_not_found=False)
            if group:
                users |= group.sudo().users.filtered(lambda user: user.active and not user.share)
        return users

    @api.model
    def _calls(self, start, end):
        """Calls an agent made or answered on either line. A missed call is nobody's."""
        calls = super()._calls(start, end)
        Ws = self.env['contact.centre.workspace']
        for line, (model, _direction, _status, at) in LINES.items():
            if model not in self.env or 'agent_user_id' not in self.env[model]._fields:
                continue
            found = self.env[model].sudo().search(
                [(at, '>=', start), (at, '<', end), ('agent_user_id', '!=', False)])
            for call in found:
                kind, _words = Ws._call_outcome(line, call)
                if kind == 'missed':
                    continue
                row = calls.setdefault(call.agent_user_id.id, [0, 0])
                row[0] += 1
                if kind == 'answered' and call.duration:
                    row[1] += call.duration
        return calls

    @api.model
    def _backlog(self, source):
        rows = super()._backlog(source)
        if source not in (SOURCE, 'both'):
            return rows
        week = fields.Datetime.now() - timedelta(days=7)
        Item = self.env['contact.centre.queue.item'].sudo()
        return rows + [{
            'key': 'queue',
            'label': self.env._("calls waiting in the queues"),
            'waiting': Item.search_count([('state', '=', 'open')]),
            'done': self.env['comm.agent.activity'].sudo().search_count(
                [('action', '=', 'queue_call'), ('at', '>=', week)]),
            'new': Item.search_count([('create_date', '>=', week)]),
            'action': 'queue_call',
        }]
