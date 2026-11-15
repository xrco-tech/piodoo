# -*- coding: utf-8 -*-
"""Calls waiting to be made, each one given to an agent.

One record is one call somebody owes a person: a callback they asked for, a
row of a running dialler campaign, a call that was missed, or a follow-up an
agent set for themselves. Nothing here places a call.

Records are made by `_queue_pull`, which looks at where such calls come from
(the dialler's call lists, Chat2Work callback requests when that addon is
installed, call outcomes of the Callback kind, missed calls) rather than
hooking into each of them: none of those addons knows about this one."""

import re
from datetime import timedelta

import pytz

from odoo import _, api, fields, models

AGENT = 'contact_centre.group_contact_centre_agent'
RULES = [
    ('auto', 'Share out automatically'),
    ('pool', 'Agents pick from a shared pool'),
    ('manual', 'Team lead assigns by hand'),
]
KINDS = [
    ('callback', 'Callback requested'),
    ('campaign', 'Campaign'),
    ('missed', 'Missed call'),
    ('follow', 'Follow-up'),
]
PARAM = 'contact_centre_workspace.queue_%s'
# A dialler row in one of these states needs no more calls.
DIALER_OVER = {'contacted': 'done', 'done': 'done', 'dnc': 'dnc', 'failed': 'gave_up'}
VOIP_UNANSWERED = ('no_answer', 'busy', 'failed', 'cancelled')


def tail(number):
    """The last nine digits: the same person whether typed 082… or 2782…"""
    return re.sub(r'\D', '', number or '')[-9:]


class ResUsers(models.Model):
    _inherit = 'res.users'

    cc_queue_ready = fields.Boolean(
        'Ready for Calls', copy=False,
        help="Set by the agent in My queue. Calls that are shared out automatically only go to agents who are ready.")


class CommDialerCampaign(models.Model):
    _inherit = 'comm.dialer.campaign'

    queue_assign = fields.Selection(
        RULES, 'Who Gets the Calls', default='auto', required=True,
        help="How this campaign's calls reach the agents' queues. Whichever is chosen, a team lead can still give a "
             "call to a named agent or move it to someone else from Team queues.")
    queue_agent_ids = fields.Many2many(
        'res.users', 'comm_dialer_campaign_queue_agent_rel', 'campaign_id', 'user_id', 'Agents on This Campaign',
        domain=lambda self: [('groups_id', 'in', self.env.ref(AGENT).id)],
        help="The agents whose queues this campaign's calls go to. Empty means every Contact Centre agent.")


class ContactCentreQueueItem(models.Model):
    _name = 'contact.centre.queue.item'
    _description = 'Contact Centre Queued Call'
    _order = 'due_at, id'

    name = fields.Char('Person', required=True)
    phone = fields.Char(index=True)
    partner_id = fields.Many2one('res.partner', 'Contact', ondelete='set null')
    contact_id = fields.Many2one('contact.centre.contact', 'Conversation', ondelete='set null')
    kind = fields.Selection(KINDS, required=True, default='follow', index=True)
    origin = fields.Char('From', help="Where the call came from: a campaign's name, Chat2Work, a call outcome.")
    # What this call was made from, e.g. dialer-12, c2w-7, wa-340: so it is not made twice.
    source_ref = fields.Char(index=True, copy=False)
    note = fields.Text('Why')
    log = fields.Text('What Happened So Far', copy=False)

    due_at = fields.Datetime('Due', required=True, default=fields.Datetime.now, index=True)
    # A time somebody committed to (a callback at 15:00, a retry) rather than "as soon as you can".
    timed = fields.Boolean()
    user_id = fields.Many2one('res.users', 'Assigned To', ondelete='set null', index=True)
    assigned_by_id = fields.Many2one('res.users', 'Assigned By', ondelete='set null')
    assigned_at = fields.Datetime()

    state = fields.Selection([('open', 'To call'), ('done', 'Closed')], default='open', required=True, index=True)
    outcome = fields.Selection([
        ('done', 'Spoke to them'), ('gave_up', 'No answer after every try'),
        ('dnc', 'Do not call again'), ('cancelled', 'No longer needed'),
    ], copy=False)
    attempts = fields.Integer('Tries', default=0, copy=False)
    max_attempts = fields.Integer('Tries Allowed', default=3)
    last_attempt_at = fields.Datetime(copy=False)
    done_at = fields.Datetime(copy=False)
    done_by_id = fields.Many2one('res.users', 'Closed By', ondelete='set null', copy=False)

    dialer_contact_id = fields.Many2one('comm.dialer.contact', 'Call List Row', ondelete='cascade', index=True)
    dialer_campaign_id = fields.Many2one(related='dialer_contact_id.campaign_id', store=True, string='Dialler Campaign')
    # The Chat2Work callback request this came from (an id: that addon may not be installed).
    c2w_callback_id = fields.Integer('Chat2Work Callback', copy=False)

    # ── Settings ─────────────────────────────────────────────────────────
    @api.model
    def _param(self, name, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM % name, default)

    @api.model
    def _set_param(self, name, value):
        self.env['ir.config_parameter'].sudo().set_param(PARAM % name, value)

    @api.model
    def _default_rule(self):
        """How calls that belong to no campaign reach the agents."""
        rule = self._param('assign', 'auto')
        return rule if rule in dict(RULES) else 'auto'

    def _rule(self):
        self.ensure_one()
        campaign = self.dialer_campaign_id
        return campaign.queue_assign if campaign else self._default_rule()

    @api.model
    def _all_agents(self):
        group = self.env.ref(AGENT)
        return self.env['res.users'].sudo().search([('groups_id', 'in', group.id), ('share', '=', False)])

    def _agents(self):
        """The agents this call may go to."""
        self.ensure_one()
        return self.dialer_campaign_id.queue_agent_ids or self._all_agents()

    # ── Assigning ────────────────────────────────────────────────────────
    @api.model
    def _notify(self, users):
        """Tell these agents' screens that their queue changed."""
        bus = self.env['bus.bus'].sudo()
        for user in users:
            if user.partner_id:
                bus._sendone(user.partner_id, 'contact_centre_queue', {})

    def _assign(self, user, by=False):
        """Give these calls to `user` (or to nobody)."""
        before = self.mapped('user_id')
        self.write({
            'user_id': user.id if user else False,
            'assigned_by_id': by.id if by else False,
            'assigned_at': fields.Datetime.now() if user else False,
        })
        self._notify(before | (user or self.env['res.users']))

    @api.model
    def _load(self, users):
        """{user id: how many calls they still have to make}."""
        load = dict.fromkeys(users.ids, 0)
        if users:
            groups = self.sudo()._read_group([('state', '=', 'open'), ('user_id', 'in', users.ids)], ['user_id'], ['__count'])
            for user, count in groups:
                load[user.id] = count
        return load

    def _share(self, ready_only=True):
        """Give each of these calls to the agent with the fewest to make."""
        load = {}
        for item in self:
            agents = item._agents()
            if ready_only:
                agents = agents.filtered('cc_queue_ready')
            if not agents:
                continue
            for user in agents:
                if user.id not in load:
                    load.update(self._load(user))
            user = min(agents, key=lambda u: (load[u.id], u.id))
            item._assign(user)
            load[user.id] += 1

    @api.model
    def _auto_assign(self):
        """Calls nobody has yet, under the "share out automatically" rule."""
        waiting = self.sudo().search([('state', '=', 'open'), ('user_id', '=', False)])
        waiting.filtered(lambda item: item._rule() == 'auto')._share()

    # ── Finding the person ───────────────────────────────────────────────
    @api.model
    def _person(self, partner=None, phone='', name=''):
        """Values that say who to call, from whatever is known about them."""
        Contact = self.env['contact.centre.contact'].sudo()
        partner = partner or self.env['res.partner']
        if not partner and len(tail(phone)) >= 7:
            # A bare number (a call-list row, a missed call) may still be someone we know.
            partner = partner.sudo().search(
                ['|', ('mobile', 'like', tail(phone)), ('phone', 'like', tail(phone))], limit=1)
        phone = phone or partner.mobile or partner.phone or ''
        contact = Contact.search([('partner_id', '=', partner.id)], limit=1) if partner else Contact
        if not contact and len(tail(phone)) >= 7:
            contact = Contact.search([('phone_number', 'like', tail(phone))], limit=1)
        if not partner and contact.partner_id:
            partner = contact.partner_id
        return {
            'name': name or partner.name or contact.name or phone or _("Unknown"),
            'phone': phone or contact.phone_number or '',
            'partner_id': partner.id,
            'contact_id': contact.id,
        }

    @api.model
    def _open_for(self, phone):
        """The call already waiting for this number, if there is one."""
        if len(tail(phone)) < 7:
            return self.browse()
        return self.sudo().search([('state', '=', 'open'), ('phone', 'like', tail(phone))], limit=1)

    @api.model
    def _known(self, refs):
        refs = list(refs)
        if not refs:
            return set()
        return set(self.sudo().search([('source_ref', 'in', refs)]).mapped('source_ref'))

    @api.model
    def _local(self, at):
        """A time as people here read it. The cron's user may have no timezone set."""
        tz = pytz.timezone(self.env.user.tz or self._context.get('tz') or 'Africa/Johannesburg')
        return pytz.utc.localize(at).astimezone(tz)

    def _add_log(self, text):
        stamp = self._local(fields.Datetime.now()).strftime('%d %b %H:%M').lstrip('0')
        for item in self:
            item.log = '\n'.join(filter(None, [item.log, '%s · %s' % (stamp, text)]))

    def _close(self, outcome, user=False):
        self.write({'state': 'done', 'outcome': outcome, 'done_at': fields.Datetime.now(),
                    'done_by_id': user.id if user else False})
        self._notify(self.mapped('user_id'))

    # ── Collecting the calls ─────────────────────────────────────────────
    @api.model
    def _queue_pull(self, force=False):
        """Bring the queue up to date with where calls come from, then share
        out what is waiting. Cheap to call often: it does the work at most
        every 30 seconds unless `force`d."""
        self = self.sudo()
        now = fields.Datetime.now()
        last = self._param('pulled_at')
        if not force and last and fields.Datetime.to_datetime(last) > now - timedelta(seconds=30):
            return False
        # Calls missed before this was installed are history, not a queue.
        since = fields.Datetime.to_datetime(self._param('since') or False)
        if not since:
            since = now
            self._set_param('since', fields.Datetime.to_string(now))
        self._set_param('pulled_at', fields.Datetime.to_string(now))
        self._pull_campaigns()
        self._pull_chat2work()
        self._pull_outcome_callbacks(since)
        self._pull_missed(since)
        self._auto_assign()
        return True

    @api.model
    def _cron_queue_pull(self):
        self._queue_pull(force=True)

    @api.model
    def _pull_campaigns(self):
        Row = self.env['comm.dialer.contact'].sudo()
        # Rows that are finished, or whose campaign is, come off the queue.
        for item in self.search([('state', '=', 'open'), ('dialer_contact_id', '!=', False)]):
            row = item.dialer_contact_id
            campaign = row.campaign_id
            if row.state in DIALER_OVER:
                item._close(DIALER_OVER[row.state])
            elif campaign.state == 'done' or not campaign.active:
                item._close('cancelled')
            elif row.attempts != item.attempts or (row.next_attempt and row.next_attempt != item.due_at):
                # The dialler tried this one itself.
                item.write({'attempts': row.attempts, 'due_at': row.next_attempt or item.due_at,
                            'timed': bool(row.next_attempt)})
        rows = Row.search([('campaign_id.state', '=', 'running'), ('campaign_id.active', '=', True),
                           ('state', 'in', ('pending', 'retry'))])
        queued = set(self.search([('state', '=', 'open'), ('dialer_contact_id', 'in', rows.ids)]).dialer_contact_id.ids)
        for row in rows:
            campaign = row.campaign_id
            if row.id in queued or row.attempts >= campaign.max_attempts:
                continue
            vals = self._person(row.partner_id, row.number)
            vals.update({
                'kind': 'campaign', 'origin': campaign.name, 'source_ref': 'dialer-%s' % row.id,
                'note': row.notes or False, 'dialer_contact_id': row.id,
                'due_at': row.next_attempt or fields.Datetime.now(), 'timed': bool(row.next_attempt),
                'attempts': row.attempts, 'max_attempts': campaign.max_attempts,
            })
            self.create(vals)

    @api.model
    def _pull_chat2work(self):
        if 'chat2work.callback.request' not in self.env:
            return
        Callback = self.env['chat2work.callback.request'].sudo()
        for item in self.search([('state', '=', 'open'), ('c2w_callback_id', '!=', 0)]):
            callback = Callback.browse(item.c2w_callback_id).exists()
            if not callback or callback.state in ('done', 'cancelled'):
                item._close('done' if callback.state == 'done' else 'cancelled')
        callbacks = Callback.search([('state', 'in', ('new', 'in_progress'))])
        known = self._known('c2w-%s' % c.id for c in callbacks)
        for callback in callbacks:
            if 'c2w-%s' % callback.id in known:
                continue
            name = callback.candidate_id.display_name if callback.candidate_id else ''
            vals = self._person(callback.partner_id, callback.phone, name)
            via = {'ussd': 'USSD', 'whatsapp': 'WhatsApp', 'web': _("the CV page")}.get(callback.channel, callback.channel or '')
            vals.update({
                'kind': 'callback', 'origin': 'Chat2Work', 'source_ref': 'c2w-%s' % callback.id,
                'note': '\n'.join(filter(None, [_("Asked in Chat2Work, by %s.", via) if via else _("Asked in Chat2Work."),
                                                callback.notes])),
                'due_at': callback.create_date, 'c2w_callback_id': callback.id,
            })
            self.create(vals)

    @api.model
    def _pull_outcome_callbacks(self, since):
        """A WhatsApp call wrapped up with an outcome of the Callback kind."""
        calls = self.env['whatsapp.call.log'].sudo().search([
            ('disposition_id.category', '=', 'callback'), ('write_date', '>=', since)])
        known = self._known('wacb-%s' % c.id for c in calls)
        for call in calls:
            if 'wacb-%s' % call.id in known:
                continue
            number = call.from_number if call.call_direction == 'incoming' else call.to_number
            vals = self._person(call.partner_id, number)
            vals.update({
                'kind': 'callback', 'origin': _("Call outcome: %s", call.disposition_id.name),
                'source_ref': 'wacb-%s' % call.id, 'note': call.disposition_note or False,
                'due_at': fields.Datetime.now(),
            })
            item = self.create(vals)
            # The agent who promised the callback keeps it.
            if call.agent_user_id:
                item._assign(call.agent_user_id)

    @api.model
    def _pull_missed(self, since):
        recent = max(since, fields.Datetime.now() - timedelta(days=2))
        found = []
        for call in self.env['whatsapp.call.log'].sudo().search(
                [('is_missed', '=', True), ('call_timestamp', '>=', recent)], order='call_timestamp'):
            found.append(('wa-%s' % call.id, call.partner_id, call.from_number, call.call_timestamp, 'WhatsApp', 'WhatsApp'))
        if 'comm.voip.call' in self.env:
            for call in self.env['comm.voip.call'].sudo().search(
                    [('direction', '=', 'incoming'), ('state', 'in', VOIP_UNANSWERED), ('start_time', '>=', recent)],
                    order='start_time'):
                found.append(('voip-%s' % call.id, call.partner_id, call.from_number, call.start_time, _("the phone line"), _("Phone line")))
        known = self._known(ref for ref, *_rest in found)
        for ref, partner, number, at, line, origin in sorted(found, key=lambda f: f[3]):
            if ref in known or not number:
                continue
            clock = self._local(at).strftime('%H:%M')
            waiting = self._open_for(number)
            if waiting:
                # They are already owed a call: note that they rang again.
                waiting._add_log(_("Rang again on %(line)s at %(time)s, nobody answered.", line=line, time=clock))
                waiting.source_ref = waiting.source_ref or ref
                self.create(dict(self._person(partner, number), kind='missed', source_ref=ref, state='done',
                                 outcome='cancelled', done_at=fields.Datetime.now(), due_at=at,
                                 note=_("Counted with the call already waiting for this person.")))
                continue
            vals = self._person(partner, number)
            vals.update({
                'kind': 'missed', 'origin': origin, 'source_ref': ref, 'due_at': at,
                'note': _("Rang on %(line)s at %(time)s, nobody answered.", line=line, time=clock),
            })
            self.create(vals)
