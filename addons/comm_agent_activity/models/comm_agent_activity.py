# -*- coding: utf-8 -*-
"""One line per thing an agent does that counts, and the points each is worth."""
import logging

from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

SOURCES = [('chat2work', 'Chat2Work'), ('contact_centre', 'Contact Centre')]
ACTIONS = [
    ('employer_check', 'Employer checked'),
    ('employer_join', 'Employers joined'),
    ('job_check', 'Job checked'),
    ('match', 'Match decided'),
    ('reply', 'Reply sent'),
    ('outreach', 'Message sent, not a reply'),
    ('close', 'Conversation closed'),
    ('queue_call', 'Queued call wrapped up'),
]
# What points can be set for: the actions, plus two things that are not lines here.
SCORED = ACTIONS + [
    ('call', 'Call made or answered'),
    ('reversed', 'Decision reversed later'),
]
# A longer gap than this since the agent's last action says nothing about how long this one took.
MAX_TAKEN = 30 * 60


class CommAgentActivity(models.Model):
    _name = 'comm.agent.activity'
    _description = 'Agent activity'
    _order = 'at desc, id desc'

    user_id = fields.Many2one('res.users', 'Agent', required=True, index=True, ondelete='cascade')
    at = fields.Datetime('When', required=True, index=True, default=fields.Datetime.now)
    source = fields.Selection(SOURCES, required=True, index=True)
    action = fields.Selection(ACTIONS, required=True, index=True)
    res_model = fields.Char('Record model', index=True)
    res_id = fields.Integer('Record id', index=True)
    name = fields.Char('Record')
    result = fields.Char(help="The answer the agent gave, as the record keeps it. For example: verified.")
    result_label = fields.Char('Result')
    has_note = fields.Boolean('With a note')
    seconds = fields.Integer('Seconds since their last action',
                             help="Empty when the agent's last action was more than 30 minutes before.")
    wait_seconds = fields.Integer('Seconds the person waited')
    reversed = fields.Boolean('Reversed later', index=True)
    reversed_by_id = fields.Many2one('res.users', 'Reversed by', ondelete='set null')
    reversed_at = fields.Datetime()

    @api.model
    def _counts(self):
        """Whether what the current user does is an agent's work: not the system, not a portal user."""
        return self.env.uid != SUPERUSER_ID and not self.env.user.share \
            and not self.env.context.get('agent_activity_off')

    @api.model
    def _log(self, action, source, record=None, name=None, result=None, label=None, has_note=False, wait=None):
        """Note that the current user did `action`. Never stops the action itself."""
        if not self._counts():
            return self.browse()
        try:
            with self.env.cr.savepoint():
                Log = self.sudo()
                now = fields.Datetime.now()
                last = Log.search([('user_id', '=', self.env.uid)], order='at desc, id desc', limit=1)
                taken = (now - last.at).total_seconds() if last else None
                return Log.create({
                    'user_id': self.env.uid,
                    'at': now,
                    'source': source,
                    'action': action,
                    'res_model': record._name if record else False,
                    'res_id': record.id if record else False,
                    'name': (name or (record.display_name if record else '') or '')[:200],
                    'result': result or False,
                    'result_label': label or False,
                    'has_note': bool(has_note),
                    'seconds': max(1, round(taken)) if taken is not None and taken <= MAX_TAKEN else False,
                    'wait_seconds': max(1, round(wait)) if wait else False,
                })
        except Exception:      # noqa: BLE001 - a report line must never break an agent's work
            _logger.exception("Agent activity: could not record %s", action)
            return self.browse()

    @api.model
    def _reverse(self, action, record, result=None):
        """Someone changes a decision: if the last one on this record was another
        agent's and said something else, it counts as reversed."""
        if not self._counts() or not record:
            return
        try:
            with self.env.cr.savepoint():
                last = self.sudo().search(
                    [('action', '=', action), ('res_model', '=', record._name), ('res_id', '=', record.id)],
                    order='at desc, id desc', limit=1)
                if last and not last.reversed and last.user_id != self.env.user and last.result != result:
                    last.write({'reversed': True, 'reversed_by_id': self.env.uid, 'reversed_at': fields.Datetime.now()})
        except Exception:      # noqa: BLE001
            _logger.exception("Agent activity: could not mark %s as reversed", action)


class CommAgentActivityPoints(models.Model):
    _name = 'comm.agent.activity.points'
    _description = 'Points for an agent action'
    _order = 'points desc, id'
    _rec_name = 'action'

    action = fields.Selection(SCORED, required=True)
    points = fields.Float(required=True, default=0.0)

    _sql_constraints = [('action_unique', 'unique(action)', 'Each action has one number of points.')]

    @api.model
    def _all(self):
        """{action: points}, with 0 for an action nobody has set."""
        points = dict.fromkeys((key for key, _label in SCORED), 0.0)
        points.update({row.action: row.points for row in self.sudo().search([])})
        return points
