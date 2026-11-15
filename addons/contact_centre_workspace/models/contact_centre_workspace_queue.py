# -*- coding: utf-8 -*-
"""What the My queue and Team queues sections of the workspace read and do.

My queue is one agent's calls to make. Team queues is the team lead's view of
everyone's, with assigning. Queue records are read with sudo after checking
who is asking: an agent sees their own calls, a manager sees all of them."""

from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .contact_centre_workspace import COLOURS
from .contact_centre_queue import KINDS, RULES, tail

MANAGER = 'contact_centre.group_contact_centre_manager'
RETRY_HOURS = 2.0
# How long a call with no set time may wait before it counts as overdue.
PATIENCE = {'callback': 60, 'missed': 30, 'follow': 5}


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    def _q(self):
        return self.env['contact.centre.queue.item'].sudo()

    def _lead(self):
        self._agent()
        if not self.env.user.has_group(MANAGER):
            raise AccessError(_("Only Contact Centre managers can see the team's queues."))

    @api.model
    def _queue_item(self, item_id):
        item = self._q().search([('id', '=', int(item_id or 0))], limit=1)
        if not item:
            raise UserError(_("This call is no longer in the queue."))
        if item.user_id != self.env.user and not self.env.user.has_group(MANAGER):
            raise AccessError(_("This call is in someone else's queue."))
        return item

    @api.model
    def _today_start(self):
        """Midnight today in the user's timezone, as a UTC datetime."""
        tz = pytz.timezone(self.env.user.tz or 'Africa/Johannesburg')
        local = datetime.combine(datetime.now(tz).date(), time.min)
        return tz.localize(local).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _queue_late(self, item, now):
        """Minutes this call is overdue by, or 0."""
        if item.kind == 'campaign' and not item.timed:
            return 0
        grace = 5 if item.timed else PATIENCE.get(item.kind, 60)
        late = int((now - item.due_at).total_seconds() // 60)
        return late if late >= grace else 0

    @api.model
    def _wa_allowed(self, phones):
        """The numbers (as given) that have allowed WhatsApp calls."""
        Permission = self.env['whatsapp.call.permission'].sudo()
        account = Permission._resolve_account()
        wanted = {Permission._normalise_phone(phone): phone for phone in phones if phone}
        if not wanted or not account.phone_number_id:
            return set()
        granted = Permission.search([('phone', 'in', list(wanted)), ('phone_number_id', '=', account.phone_number_id)])
        return {wanted[p.phone] for p in granted if p.current_state == 'granted'}

    @api.model
    def _queue_row(self, item, now, today_end, allowed):
        late = self._queue_late(item, now)
        campaign = item.dialer_campaign_id
        return {
            'id': item.id,
            'name': item.name,
            'phone': item.phone or '',
            'initials': self._initials(item.name),
            'colour': COLOURS[(item.partner_id.id or item.id) % len(COLOURS)],
            'kind': item.kind,
            'reason': campaign.name if item.kind == 'campaign' and campaign else dict(
                self.env['contact.centre.queue.item']._fields['kind']._description_selection(self.env))[item.kind],
            'from_c2w': bool(item.c2w_callback_id),
            'due': fields.Datetime.to_string(item.due_at),
            'late': late,
            'group': 'overdue' if late else 'now' if item.due_at <= now else 'today' if item.due_at < today_end else 'later',
            'wa': item.phone in allowed,
            'attempts': item.attempts,
            'max': item.max_attempts,
            # A campaign the dialler rings for the agent.
            'auto': bool(campaign) and campaign.mode != 'preview',
            'note': self._preview(item.note),
            'user_id': item.user_id.id,
            'user': item.user_id.name or '',
        }

    @api.model
    def _queue_rows(self, items):
        now = fields.Datetime.now()
        today_end = self._today_start() + timedelta(days=1)
        allowed = self._wa_allowed(items.mapped('phone'))
        rows = [self._queue_row(item, now, today_end, allowed) for item in items]
        order = {'overdue': 0, 'now': 1, 'today': 2, 'later': 3}
        rows.sort(key=lambda row: (order[row['group']], row['due'], row['id']))
        return rows

    @api.model
    def _queue_done_today(self, users=None):
        """{user id: calls they closed today}, leaving out ones that were only tidied away."""
        domain = [('state', '=', 'done'), ('outcome', '!=', 'cancelled'), ('done_at', '>=', self._today_start()),
                  ('done_by_id', '!=', False)]
        if users is not None:
            domain.append(('done_by_id', 'in', users.ids))
        return {user.id: count for user, count in self._q()._read_group(domain, ['done_by_id'], ['__count'])}

    @api.model
    def _queue_pool(self, user):
        """Calls waiting in a shared pool that this agent may take."""
        waiting = self._q().search([('state', '=', 'open'), ('user_id', '=', False)], order='due_at, id')
        return waiting.filtered(lambda item: item._rule() == 'pool' and user in item._agents())

    @api.model
    def _queue_agents(self):
        return [{'id': user.id, 'name': user.name} for user in self._q()._all_agents().sorted('name')]

    # ── Counts for the rail ──────────────────────────────────────────────
    @api.model
    def ws_counts(self):
        counts = super().ws_counts()
        Queue = self._q()
        counts['queue'] = Queue.search_count([('state', '=', 'open'), ('user_id', '=', self.env.uid)])
        if self.env.user.has_group(MANAGER):
            counts['unassigned'] = Queue.search_count([('state', '=', 'open'), ('user_id', '=', False)])
        return counts

    @api.model
    def ws_boot(self):
        boot = super().ws_boot()
        boot['lead'] = self.env.user.has_group(MANAGER)
        return boot

    # ── My queue ─────────────────────────────────────────────────────────
    @api.model
    def ws_queue(self, pill='all'):
        self._agent()
        user = self.env.user
        Queue = self._q()
        Queue._queue_pull()
        mine = Queue.search([('state', '=', 'open'), ('user_id', '=', user.id)])
        rows = self._queue_rows(mine)
        counts = {'all': len(rows)}
        for kind, _label in KINDS:
            counts[kind] = len([row for row in rows if row['kind'] == kind])
        done = self._queue_done_today(user).get(user.id, 0)
        return {
            'ready': user.cc_queue_ready,
            'rows': [row for row in rows if pill in ('all', row['kind'])],
            'counts': counts,
            'overdue': len([row for row in rows if row['late']]),
            'done': done,
            'pool': len(self._queue_pool(user)),
            'agents': self._queue_agents(),
        }

    @api.model
    def ws_queue_item(self, item_id):
        self._agent()
        item = self._queue_item(item_id)
        now = fields.Datetime.now()
        row = self._queue_rows(item)[0]

        permission = ''
        if item.phone:
            status = self.env['whatsapp.call.permission'].sudo()._status_for(item.phone, name=item.name)
            permission = status.get('message') or _("%s has not been asked whether we may call on WhatsApp.", item.name)

        # The last few times we were in touch: calls on either line, and the last message.
        history = []
        if item.partner_id:
            who = [('partner_id', '=', item.partner_id.id)]
        elif len(tail(item.phone)) >= 7:
            who = ['|', ('from_number', 'ilike', tail(item.phone)), ('to_number', 'ilike', tail(item.phone))]
        else:
            who = None
        if who:
            for call in self.sudo()._calls(limit=3, extra={'wa': who, 'voip': who}):
                line = 'WhatsApp' if call['line'] == 'whatsapp' else _("Phone")
                words = _("%(line)s call, %(status)s", line=line, status=call['status'].lower())
                if call['duration']:
                    words += ', ' + call['duration']
                if call['disposition']:
                    words += _(', outcome "%s"', call['disposition'])
                history.append({'key': call['key'], 'at': call['at'], 'text': words})
        if item.contact_id:
            last = self.sudo()._last_messages(item.contact_id.ids).get(item.contact_id.id)
            if last and last[0] != 'voice' and last[2]:
                who_said = _("We wrote") if last[1] == 'outbound' else _("They wrote")
                history.append({'key': 'msg', 'at': fields.Datetime.to_string(last[3]),
                                'text': '%s: %s' % (who_said, self._preview(last[2]))})
        history.sort(key=lambda h: h['at'], reverse=True)

        campaign = item.dialer_campaign_id
        row.update({
            'full_note': item.note or '',
            'origin': item.origin or '',
            'assigned_by': item.assigned_by_id.name or '',
            'assigned_at': fields.Datetime.to_string(item.assigned_at) if item.assigned_at else False,
            'last_attempt': fields.Datetime.to_string(item.last_attempt_at) if item.last_attempt_at else False,
            'log': [line for line in (item.log or '').split('\n') if line],
            'permission': permission,
            'history': history[:4],
            'contact_id': item.contact_id.id,
            'partner_id': item.partner_id.id,
            'script': {'id': campaign.voice_chatbot_id.id, 'name': campaign.voice_chatbot_id.name}
                      if campaign.voice_chatbot_id else False,
            'mine': item.user_id == self.env.user,
            'now': fields.Datetime.to_string(now),
        })
        return row

    @api.model
    def ws_queue_ready(self, ready):
        """The agent's "Ready for calls" switch. For a campaign the dialler
        rings for them, it also readies or pauses their dialler session."""
        self._agent()
        user = self.env.user
        user.sudo().cc_queue_ready = bool(ready)
        Session = self.env['comm.dialer.agent.session'].sudo()
        session = Session.search([('user_id', '=', user.id)], limit=1)
        if ready:
            campaign = self.env['comm.dialer.campaign'].sudo().search([
                ('state', '=', 'running'), ('mode', '!=', 'preview'), ('queue_agent_ids', 'in', user.id)], limit=1)
            if campaign and user.sudo().dialer_sip_ext:
                session = session or Session.create({'user_id': user.id})
                if session.state in ('offline', 'paused', 'ready'):
                    session.write({'campaign_id': campaign.id})
                    session._set_state('ready')
        elif session.state == 'ready':
            session._set_state('paused')
        self._q()._auto_assign()
        return self.ws_queue()

    @api.model
    def ws_queue_take(self):
        """Take the next call from the shared pool."""
        self._agent()
        pool = self._queue_pool(self.env.user)
        if not pool:
            raise UserError(_("There is nothing left in the shared pool."))
        # Two agents pressing at once must not get the same call.
        self._q().flush_model()
        self.env.cr.execute("SELECT id FROM contact_centre_queue_item WHERE id IN %s AND user_id IS NULL "
                            "ORDER BY due_at, id LIMIT 1 FOR UPDATE SKIP LOCKED", [tuple(pool.ids)])
        found = self.env.cr.fetchone()
        if not found:
            raise UserError(_("Someone else just took that call. Try again."))
        item = self._q().browse(found[0])
        item._assign(self.env.user, by=self.env.user)
        return item.id

    @api.model
    def ws_queue_outcome(self, item_id, outcome, note='', when=False, user_id=False):
        """What happened with a call: done | no_answer | later | hand | dnc."""
        self._agent()
        item = self._queue_item(item_id)
        if item.state != 'open':
            raise UserError(_("This call is already closed."))
        user = self.env.user
        note = (note or '').strip()
        row = item.dialer_contact_id
        now = fields.Datetime.now()
        callback = self.env['chat2work.callback.request'].sudo().browse(item.c2w_callback_id).exists() \
            if item.c2w_callback_id and 'chat2work.callback.request' in self.env else None

        def said(text):
            item._add_log('%s: %s%s' % (user.name, text, ' – ' + note if note else ''))

        if outcome == 'done':
            said(_("spoke to them"))
            item.write({'attempts': item.attempts + 1, 'last_attempt_at': now})
            if row:
                row.write({'attempts': row.attempts + 1})
                row.register_result('contacted')
            if callback:
                callback.write({'state': 'done'})
            item._close('done', user)
        elif outcome == 'no_answer':
            said(_("no answer"))
            attempts = item.attempts + 1
            item.write({'attempts': attempts, 'last_attempt_at': now})
            if row:
                row.write({'attempts': row.attempts + 1})
                row.register_result('no_answer')
                attempts = row.attempts
                item.attempts = attempts
            if callback and callback.state == 'new':
                callback.write({'state': 'in_progress'})
            if attempts >= item.max_attempts or (row and row.state == 'failed'):
                item._close('gave_up', user)
            else:
                gap = row.campaign_id.retry_gap_hours if row else RETRY_HOURS
                item.write({'due_at': (row.next_attempt if row else False) or now + timedelta(hours=gap), 'timed': True})
        elif outcome == 'later':
            due = fields.Datetime.to_datetime(when) if when else False
            if not due or due <= now:
                raise UserError(_("Pick a time that is still to come."))
            said(_("to call back at the time set"))
            item.write({'due_at': due, 'timed': True})
            if row:
                row.write({'state': 'retry', 'next_attempt': due})
        elif outcome == 'hand':
            other = self.env['res.users'].sudo().browse(int(user_id or 0)).exists()
            if other and other not in self._q()._all_agents():
                raise UserError(_("That person is not a Contact Centre agent."))
            said(_("handed to %s", other.name) if other else _("put back as unassigned"))
            item._assign(other, by=user)
        elif outcome == 'dnc':
            said(_("asked not to be called again"))
            if row:
                row.register_result('dnc')
            elif item.phone and not self.env['comm.dialer.dnc'].sudo().search_count([('number', '=', item.phone)]):
                self.env['comm.dialer.dnc'].sudo().create({
                    'number': item.phone, 'partner_id': item.partner_id.id or False,
                    'reason': _("Asked not to be called again (%s)", user.name)})
            if callback:
                callback.write({'state': 'cancelled'})
            item._close('dnc', user)
        else:
            raise UserError(_("Unknown outcome."))
        return True

    @api.model
    def ws_queue_people(self, term=''):
        """People to set a follow-up for."""
        self._agent()
        term = (term or '').strip()
        if len(term) < 2:
            return []
        contacts = self.env['contact.centre.contact'].search(
            ['|', ('name', 'ilike', term), ('phone_number', 'ilike', term)], limit=8)
        return [{'id': c.id, 'name': c.name or c.phone_number or '', 'phone': c.phone_number or ''} for c in contacts]

    @api.model
    def ws_queue_follow_up(self, contact_id, when, note=''):
        """A follow-up call the agent sets for themselves."""
        self._agent()
        contact = self._contact(contact_id)
        due = fields.Datetime.to_datetime(when) if when else False
        if not due or due <= fields.Datetime.now():
            raise UserError(_("Pick a time that is still to come."))
        if not contact.phone_number:
            raise UserError(_("This contact has no phone number."))
        Queue = self._q()
        vals = Queue._person(contact.partner_id, contact.phone_number, contact.name)
        vals.update({'contact_id': contact.id, 'kind': 'follow', 'origin': _("Set by %s", self.env.user.name),
                     'note': (note or '').strip() or False, 'due_at': due, 'timed': True})
        item = Queue.create(vals)
        item._assign(self.env.user, by=self.env.user)
        return item.id

    # ── Team queues ──────────────────────────────────────────────────────
    @api.model
    def _on_call(self, users):
        """The agents (ids) who are on a call right now."""
        busy = set()
        recent = fields.Datetime.now() - timedelta(hours=3)
        wa = self.env['whatsapp.call.log'].sudo().search([
            ('agent_user_id', 'in', users.ids), ('call_status', '=', 'answered'),
            ('end_timestamp', '=', False), ('call_timestamp', '>=', recent)])
        busy.update(wa.mapped('agent_user_id').ids)
        voip = self.env['comm.voip.call'].sudo().search([
            ('agent_user_id', 'in', users.ids), ('state', '=', 'in_progress'), ('start_time', '>=', recent)])
        busy.update(voip.mapped('agent_user_id').ids)
        return busy

    @api.model
    def ws_team(self, user_id=False):
        """Everyone's queues. `user_id` False shows the calls nobody has."""
        self._lead()
        Queue = self._q()
        Queue._queue_pull()
        now = fields.Datetime.now()
        agents = Queue._all_agents().sorted('name')
        waiting = Queue.search([('state', '=', 'open')])
        rows = self._queue_rows(waiting)
        done = self._queue_done_today()
        busy = self._on_call(agents)

        def person(user):
            mine = [row for row in rows if row['user_id'] == (user.id if user else False)]
            closed = done.get(user.id, 0) if user else 0
            return {
                'id': user.id if user else False,
                'name': user.name if user else _("Unassigned"),
                'initials': self._initials(user.name) if user else '?',
                'colour': COLOURS[user.id % len(COLOURS)] if user else '',
                'state': 'none' if not user else 'call' if user.id in busy else 'ready' if user.cc_queue_ready else 'away',
                'todo': len(mine),
                'late': len([row for row in mine if row['late']]),
                'done': closed,
                'total': closed + len(mine),
            }

        selected = int(user_id or 0)
        people = [person(False)] + [person(user) for user in agents]
        campaigns = self.env['comm.dialer.campaign'].sudo().search([('state', '!=', 'done')])
        rule_labels = dict(campaigns._fields['queue_assign']._description_selection(self.env))
        return {
            'tiles': {
                'waiting': len(rows),
                'overdue': len([row for row in rows if row['late']]),
                'unassigned': len([row for row in rows if not row['user_id']]),
                'done': sum(done.values()),
            },
            'people': people,
            'selected': selected or False,
            'rows': [row for row in rows if row['user_id'] == (selected or False)],
            'agents': [{'id': p['id'], 'name': p['name'], 'todo': p['todo']} for p in people if p['id']],
            'rule': Queue._default_rule(),
            'rules': [{'key': key, 'label': rule_labels[key]} for key, _label in RULES],
            'campaigns': [{
                'id': c.id, 'name': c.name, 'rule': rule_labels[c.queue_assign],
                'dials': _("Agent clicks to call") if c.mode == 'preview' else _("Dialler rings"),
                'running': c.state == 'running',
            } for c in campaigns],
            'now': fields.Datetime.to_string(now),
        }

    @api.model
    def ws_team_assign(self, item_ids, user_id=False):
        """Give these calls to an agent, or put them back as unassigned."""
        self._lead()
        items = self._q().search([('id', 'in', [int(i) for i in item_ids or []]), ('state', '=', 'open')])
        user = self.env['res.users'].sudo().browse(int(user_id or 0)).exists()
        if user and user not in self._q()._all_agents():
            raise UserError(_("That person is not a Contact Centre agent."))
        who = _("assigned to %s", user.name) if user else _("put back as unassigned")
        items._add_log('%s: %s' % (self.env.user.name, who))
        items._assign(user, by=self.env.user)
        return True

    @api.model
    def ws_team_share(self):
        """Share the unassigned calls out evenly: among agents who are ready,
        or among all of a call's agents when none of them is."""
        self._lead()
        waiting = self._q().search([('state', '=', 'open'), ('user_id', '=', False)])
        waiting._share(ready_only=True)
        left = waiting.filtered(lambda item: not item.user_id)
        left._share(ready_only=False)
        return len(waiting) - len(left.filtered(lambda item: not item.user_id))

    @api.model
    def ws_team_rule(self, rule):
        """How calls outside a campaign reach the agents."""
        self._lead()
        if rule not in dict(RULES):
            raise UserError(_("Unknown setting."))
        self._q()._set_param('assign', rule)
        self._q()._auto_assign()
        return True
