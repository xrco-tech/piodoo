# -*- coding: utf-8 -*-
"""Data for the Chat2Work workspace screen.

One read call per pane, so the screen never assembles a candidate from a
dozen requests. Changes go through the existing models and their actions
(stage, callback state, verification, ID check, call and message buttons);
nothing here writes except `ws_send`, which uses the same sender as the Send a
Message form.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.chat2work.models.chat2work_pipeline import STAGES

OPEN_CALLBACK = ('new', 'in_progress')
# A reply is owed only on channels an agent can answer on.
REPLY_CHANNELS = ('whatsapp', 'sms')
LIST_LIMIT = 100
LIST_MAX = 1000
TIMELINE_LIMIT = 300
CV_DONE = ('uploaded', 'built')
# The ID check filters on Candidates. A check has no "sent, no answer yet" state:
# "failed" is Home Affairs not confirming the ID, "waiting" is a check that didn't
# complete and has to be run again.
ID_LISTS = {
    'id_open': [('id_check_state', 'in', ('not_valid', 'failed'))],
    'id_failed': [('id_check_state', '=', 'not_valid')],
    'id_waiting': [('id_check_state', '=', 'failed')],
    'id_not_done': [('id_check_state', '=', 'none'), ('cv_state', 'in', CV_DONE)],
}
CANDIDATE_LISTS = ('no_cv', 'cv_started', 'jobs_ready')


def _dt(value):
    return fields.Datetime.to_string(value) if value else False


class Chat2workWorkspace(models.AbstractModel):
    _name = 'chat2work.workspace'
    _description = 'Chat2Work Workspace'

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _check_agent(self):
        if not self.env.user.has_group('chat2work.group_agent'):
            raise AccessError(_("You don't have access to Chat2Work."))

    @api.model
    def _page(self, offset, limit):
        """(offset, limit) for a list: a page by default, more when the screen
        reloads everything it has already loaded."""
        return max(int(offset or 0), 0), min(max(int(limit or LIST_LIMIT), 1), LIST_MAX)

    def _can_id_check(self):
        return self.env.user.has_group('chat2work_verify.group_id_check')

    def _check_id_access(self):
        self._check_agent()
        if not self._can_id_check():
            raise AccessError(_("You don't have access to ID checks."))

    @api.model
    def _label(self, record, name):
        field = record._fields[name]
        return dict(field._description_selection(self.env)).get(record[name]) or False

    @api.model
    def _selection(self, model, name):
        return [list(pair) for pair in self.env[model]._fields[name]._description_selection(self.env)]

    def _last_messages(self, partner_ids):
        """{partner_id: {'body', 'at', 'dir', 'channel', 'needs_reply'}}: each
        contact's newest entry, and whether their last WhatsApp/SMS is unanswered."""
        if not partner_ids:
            return {}
        self.env['comm.interaction'].flush_model()
        self.env['comm.conversation'].flush_model()
        self.env.cr.execute("""
            SELECT DISTINCT ON (c.partner_id)
                   c.partner_id, COALESCE(i.rendered_body, i.raw_body), i.at, i.direction, ch.code
              FROM comm_interaction i
              JOIN comm_conversation c ON c.id = i.conversation_id
              JOIN comm_channel ch ON ch.id = i.channel_id
             WHERE c.partner_id IN %s
             ORDER BY c.partner_id, i.at DESC, i.id DESC
        """, [tuple(partner_ids)])
        result = {pid: {'body': body, 'at': _dt(at), 'dir': direction, 'channel': code, 'needs_reply': False}
                  for pid, body, at, direction, code in self.env.cr.fetchall()}
        for pid in self._needs_reply_partners(partner_ids):
            result[pid]['needs_reply'] = True
        return result

    def _needs_reply_partners(self, partner_ids=None):
        """Contacts whose newest WhatsApp or SMS entry came from them."""
        self.env['comm.interaction'].flush_model()
        self.env['comm.conversation'].flush_model()
        params = [REPLY_CHANNELS]
        where = ''
        if partner_ids is not None:
            if not partner_ids:
                return []
            where = 'AND c.partner_id IN %s'
            params.append(tuple(partner_ids))
        self.env.cr.execute("""
            SELECT partner_id FROM (
                SELECT DISTINCT ON (c.partner_id) c.partner_id, i.direction
                  FROM comm_interaction i
                  JOIN comm_conversation c ON c.id = i.conversation_id
                  JOIN comm_channel ch ON ch.id = i.channel_id
                  JOIN chat2work_candidate cand ON cand.partner_id = c.partner_id AND cand.active
                 WHERE ch.code IN %s """ + where + """
                 ORDER BY c.partner_id, i.at DESC, i.id DESC) latest
             WHERE direction = 'inbound'
        """, params)
        return [row[0] for row in self.env.cr.fetchall()]

    def _candidate_row(self, candidate, last=None):
        last = last or {}
        return {
            'id': candidate.id,
            'name': candidate.display_name,
            'phone': candidate.phone or '',
            'stage': candidate.stage,
            'stage_label': self._label(candidate, 'stage'),
            'whatsapp': candidate.whatsapp_opt_in,
            'callback': bool(candidate.open_callback_count),
            'needs_reply': bool(last.get('needs_reply')),
            'preview': (last.get('body') or '').strip()[:140],
            'preview_out': last.get('dir') == 'outbound',
            'channel': last.get('channel') or False,
            'at': last.get('at') or _dt(candidate.last_active_at),
        }

    def _candidate_by_partner(self, partners):
        """{partner_id: candidate id} for bookings, which only know the contact."""
        candidates = self.env['chat2work.candidate'].search([('partner_id', 'in', partners.ids)])
        return {c.partner_id.id: c.id for c in candidates}

    # ── Start-up ─────────────────────────────────────────────────────────────

    @api.model
    def ws_bootstrap(self):
        self._check_agent()
        return {
            'stages': [list(pair) for pair in STAGES],
            'callback_states': self._selection('chat2work.callback.request', 'state'),
            'verification_states': self._selection('chat2work.listing', 'verification_state'),
            'work_states': self._selection('chat2work.listing', 'work_state'),
            'booking_states': self._selection('chat2work.interview.booking', 'state'),
            'can_id_check': self._can_id_check(),
            'user_name': self.env.user.name,
            'page_size': LIST_LIMIT,
            'counts': self.ws_counts(),
        }

    @api.model
    def ws_counts(self):
        self._check_agent()
        Candidate = self.env['chat2work.candidate']
        counts = {
            'inbox': len(self._needs_reply_partners()),
            'callbacks': self.env['chat2work.callback.request'].search_count(
                [('state', 'in', OPEN_CALLBACK), ('candidate_id', '!=', False)]),
            'jobs': self.env['chat2work.listing'].search_count([('work_state', 'in', ('to_verify', 'to_review'))]),
            # The filters on the Candidates screen.
            'lists': {key: Candidate.search_count(self._list_domain(key)) for key in self._list_keys()},
        }
        return counts

    # ── Conversations ────────────────────────────────────────────────────────

    @api.model
    def ws_inbox(self, pill='all', search='', offset=0, limit=None):
        self._check_agent()
        offset, limit = self._page(offset, limit)
        domain = []
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('phone', 'ilike', term)]
        if pill == 'reply':
            domain.append(('partner_id', 'in', self._needs_reply_partners()))
        elif pill == 'callbacks':
            domain.append(('callback_ids.state', 'in', OPEN_CALLBACK))
        elif pill == 'whatsapp':
            domain.append(('whatsapp_opt_in', '=', True))
        elif pill == 'sms':
            domain.append(('whatsapp_opt_in', '=', False))
        candidates = self.env['chat2work.candidate'].search(domain, order='last_active_at desc, id desc',
                                                            offset=offset, limit=limit)
        last = self._last_messages(candidates.partner_id.ids)
        rows = [self._candidate_row(c, last.get(c.partner_id.id)) for c in candidates]
        rows.sort(key=lambda r: r['at'] or '', reverse=True)
        return rows

    @api.model
    def ws_candidate(self, candidate_id):
        self._check_agent()
        candidate = self.env['chat2work.candidate'].browse(candidate_id).exists()
        if not candidate:
            return False
        partner = candidate.partner_id
        interactions = self.env['comm.interaction'].sudo().search(
            [('conversation_id.partner_id', '=', partner.id)], order='at desc, id desc',
            limit=TIMELINE_LIMIT) if partner else self.env['comm.interaction']
        timeline = [{
            'id': i.id,
            'dir': i.direction,
            'channel': i.channel_id.code,
            'channel_name': i.channel_id.name,
            'body': i.rendered_body or i.raw_body or '',
            'at': _dt(i.at),
            'status': i.status,
            # A USSD session's screens and replies; older sessions only have the body.
            'session': i.c2w_session or False,
        } for i in reversed(interactions)]
        callback = candidate.callback_ids.filtered(lambda c: c.state in OPEN_CALLBACK)[:1]
        message = self.env['chat2work.message'].new({'candidate_id': candidate.id})
        row = self._candidate_row(candidate, self._last_messages(partner.ids).get(partner.id))
        row.update({
            'location': candidate.location or '',
            'province': self._label(candidate, 'province'),
            'field': self._label(candidate, 'field'),
            'registered_via': candidate.registered_via or '',
            'job_seeking': candidate.job_seeking,
            'cv_state': candidate.cv_state,
            'cv_label': self._label(candidate, 'cv_state'),
            'cv_link_label': self._label(candidate, 'cv_link_state'),
            'cv_link_error': candidate.cv_link_error or '',
            'cv_unreadable': candidate.cv_text_state == 'unreadable',
            'id_check_label': self._label(candidate, 'id_check_state'),
            'id_check': self._id_check_card(candidate) if self._can_id_check() else False,
            'has_id_number': candidate.has_id_number,
            'window_open': message.window_open,
            'can_voip': candidate.c2w_can_voip,
            'call_permission': candidate.c2w_call_permission or False,
            'call_permission_note': candidate.c2w_call_permission_note or '',
            'jobs_to_review': candidate.job_match_review_count,
            'jobs_to_send': candidate.job_match_ready_count,
            'callback': {
                'id': callback.id, 'state': callback.state, 'notes': callback.notes or '',
                'channel': callback.channel or '', 'at': _dt(callback.create_date),
            } if callback else False,
            'timeline': timeline,
        })
        return row

    @api.model
    def ws_send(self, candidate_id, text, channel=None):
        """Send a typed message: WhatsApp if they use it, otherwise SMS. An agent
        can pick SMS for someone who uses WhatsApp (it has no 24-hour rule)."""
        self._check_agent()
        candidate = self.env['chat2work.candidate'].browse(candidate_id).exists()
        candidate._c2w_require_phone()
        vals = {'candidate_id': candidate.id, 'body': text}
        if channel in ('whatsapp', 'sms'):
            vals['channel'] = channel
        self.env['chat2work.message'].with_context(default_candidate_id=candidate.id).create(vals).action_send()
        return self.ws_candidate(candidate.id)

    @api.model
    def ws_cv_help(self, candidate_id):
        """The candidate's own CV page, for an agent to fill in with them (for
        example on a call, when they have no smartphone). Noted on the candidate,
        because what's entered there is saved as coming from them."""
        self._check_agent()
        candidate = self.env['chat2work.candidate'].browse(candidate_id).exists()
        if not candidate:
            return False
        token = candidate._c2w_ensure_token()
        candidate.message_post(body=_("%s opened the CV page to help with the CV.", self.env.user.name))
        # A path, not the public link: the page must load from the agent's own address to be embedded.
        return {'url': '/cv/%s' % token, 'name': candidate.display_name}

    # ── Candidates ───────────────────────────────────────────────────────────

    @api.model
    def ws_pipeline(self):
        self._check_agent()
        Candidate = self.env['chat2work.candidate']
        totals = dict(Candidate._read_group([], ['stage'], ['__count']))
        callbacks = dict(Candidate._read_group([('callback_ids.state', 'in', OPEN_CALLBACK)], ['stage'], ['__count']))
        overdue = dict(Candidate._read_group([('activity_state', '=', 'overdue')], ['stage'], ['__count']))
        no_cv = dict(Candidate._read_group([('cv_state', 'not in', CV_DONE)], ['stage'], ['__count']))
        return [{
            'id': key, 'name': label, 'total': totals.get(key, 0), 'callbacks': callbacks.get(key, 0),
            'overdue': overdue.get(key, 0), 'no_cv': no_cv.get(key, 0),
        } for key, label in STAGES]

    @api.model
    def ws_stage(self, stage, show='all', search=''):
        self._check_agent()
        domain = [('stage', '=', stage)]
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('phone', 'ilike', term)]
        domain += {
            'mine': [('activity_user_id', '=', self.env.uid)],
            'overdue': [('activity_state', '=', 'overdue')],
            'none': [('activity_ids', '=', False)],
            'callback': [('callback_ids.state', 'in', OPEN_CALLBACK)],
        }.get(show, [])
        Candidate = self.env['chat2work.candidate']
        candidates = Candidate.search(domain, order='last_active_at desc, id desc', limit=LIST_LIMIT)
        rows = []
        for c in candidates:
            tags = []
            if c.open_callback_count:
                tags.append(['warn', _("Callback requested")])
            if c.activity_state == 'overdue':
                tags.append(['warn', _("Follow-up overdue")])
            if c.cv_link_state == 'failed':
                tags.append(['warn', _("CV link failed")])
            if c.cv_state not in CV_DONE:
                tags.append(['plain', self._label(c, 'cv_state')])
            if c.job_match_ready_count:
                tags.append(['ok', _("%s jobs to send", c.job_match_ready_count)])
            row = self._candidate_row(c)
            row.update({
                'line': ' · '.join(filter(None, [self._label(c, 'province'), self._label(c, 'field'), c.location])),
                'tags': tags,
            })
            rows.append(row)
        return {'rows': rows, 'total': Candidate.search_count(domain)}

    # ── Job listings ─────────────────────────────────────────────────────────

    @api.model
    def ws_listings(self, pill='all', search='', offset=0, limit=None):
        self._check_agent()
        offset, limit = self._page(offset, limit)
        domain = [('work_state', '=', pill)] if pill != 'all' else [('work_state', 'not in', ('closed', 'rejected'))]
        term = (search or '').strip()
        if term:
            domain += ['|', ('title', 'ilike', term), ('employer', 'ilike', term)]
        listings = self.env['chat2work.listing'].search(domain, order='closing_on asc nulls last, id desc',
                                                        offset=offset, limit=limit)
        return [self._listing_row(listing) for listing in listings]

    def _listing_row(self, listing):
        return {
            'id': listing.id,
            'name': listing.title,
            'employer': listing.employer or '',
            'work_state': listing.work_state,
            'work_label': self._label(listing, 'work_state'),
            'closing_on': fields.Date.to_string(listing.closing_on) if listing.closing_on else False,
            'closing_in_days': listing.closing_in_days if listing.closing_on else False,
            'to_review': listing.suggested_count,
            'good': listing.approved_count,
        }

    @api.model
    def ws_listing(self, listing_id):
        self._check_agent()
        listing = self.env['chat2work.listing'].browse(listing_id).exists()
        if not listing:
            return False
        row = self._listing_row(listing)
        row.update({
            'location': listing.location or '',
            'provinces': ', '.join(listing.province_ids.mapped('name')),
            'field': self._label(listing, 'field'),
            'salary': listing.salary or '',
            'employment_type': listing.employment_type or '',
            'apply_url': listing.apply_url or '',
            'apply_contact': listing.apply_contact or '',
            'source': listing.source_id.name,
            'verification_state': listing.verification_state,
            'verification_note': listing.verification_note or '',
            'state': listing.state,
            'stats': [listing.sent_count, listing.opened_count, listing.feedback_good_count,
                      listing.feedback_bad_count],
            'matches': [{
                'id': m.id,
                'candidate_id': m.candidate_id.id,
                'name': m.candidate_id.display_name,
                'reason': m.reason or '',
                'state': m.state,
                'state_label': self._label(m, 'state'),
            } for m in listing.match_ids.sorted(lambda m: (m.state != 'suggested', -m.score, m.id))],
        })
        return row

    # ── Bookings ─────────────────────────────────────────────────────────────

    @api.model
    def ws_slots(self, pill='upcoming', offset=0, limit=None):
        self._check_agent()
        offset, limit = self._page(offset, limit)
        now = fields.Datetime.now()
        past = pill == 'past'
        slots = self.env['chat2work.interview.slot'].with_context(active_test=False).search(
            [('start_datetime', '<' if past else '>=', now)],
            order='start_datetime desc, id desc' if past else 'start_datetime asc, id asc',
            offset=offset, limit=limit)
        return [self._slot_row(slot) for slot in slots]

    def _slot_row(self, slot):
        live = slot.booking_ids.filtered(lambda b: b.state != 'cancelled')
        return {
            'id': slot.id,
            'name': slot.job_id.name,
            'location': slot.job_id.location or '',
            'start': _dt(slot.start_datetime),
            'capacity': slot.capacity,
            'booked': len(live),
            'open': max(slot.capacity - len(live), 0),
            'no_show': len(live.filtered(lambda b: b.state == 'no_show')),
            'available': slot.is_available,
        }

    @api.model
    def ws_slot(self, slot_id):
        self._check_agent()
        slot = self.env['chat2work.interview.slot'].with_context(active_test=False).browse(slot_id).exists()
        if not slot:
            return False
        by_partner = self._candidate_by_partner(slot.booking_ids.partner_id)
        row = self._slot_row(slot)
        row.update({
            'salary': slot.job_id.salary_text or '',
            'requirements': slot.job_id.requirements or '',
            'bookings': [{
                'id': b.id,
                'reference': b.reference,
                'name': b.partner_id.name or b.phone or _("Unknown caller"),
                'phone': b.phone or '',
                'candidate_id': by_partner.get(b.partner_id.id, False),
                'state': b.state,
                'state_label': self._label(b, 'state'),
                'channel': b.channel or '',
                'at': _dt(b.create_date),
            } for b in slot.booking_ids.sorted('create_date')],
        })
        return row

    # ── Candidate lists: the filters on Candidates, also used by the sidekick ─

    def _list_keys(self):
        return list(CANDIDATE_LISTS) + (list(ID_LISTS) if self._can_id_check() else [])

    def _list_domain(self, key):
        if key == 'no_cv':
            return [('cv_state', '=', 'none')]
        if key == 'cv_started':
            return [('cv_state', '=', 'started')]
        if key == 'jobs_ready':
            # The same rule as the candidate's "Matches to Send" count.
            matches = self.env['chat2work.listing.match'].search([
                ('state', '=', 'approved'), ('notify_state', '!=', 'sent'), ('listing_id.state', '=', 'open')])
            return [('id', 'in', matches.candidate_id.ids)]
        if key in ID_LISTS:
            self._check_id_access()
            return list(ID_LISTS[key])
        raise AccessError(_("There's no such list."))

    def _list_line(self, key, candidate):
        """Why this candidate is on the list: {'reason', 'when', 'tag'}."""
        if key in ID_LISTS:
            state = candidate.id_check_state
            latest = candidate.id_check_ids.filtered(lambda c: c.mode == 'production')[:1]
            if state == 'not_valid':
                reason = _("Home Affairs did not confirm this ID")
                detail = latest.id_status
                tag = ['bad', _("Failed")]
            elif state == 'failed':
                reason = _("The check didn't complete, run it again")
                detail = latest.error
                tag = ['warn', _("Waiting")]
            else:
                reason, detail, tag = _("CV finished, no ID check yet"), False, False
            return {'reason': '%s: %s' % (reason, detail) if detail else reason,
                    'when': _dt(candidate.id_check_at or candidate.cv_submitted_at), 'tag': tag}
        if key == 'jobs_ready':
            reason = _("%s matched job(s) ready to send", candidate.job_match_ready_count)
        elif key == 'cv_started':
            reason = _("CV started, not finished")
        else:
            reason = _("No CV yet. CV link: %s", self._label(candidate, 'cv_link_state') or _("Not sent"))
        return {'reason': reason, 'when': _dt(candidate.cv_link_sent_at or candidate.last_active_at), 'tag': False}

    @api.model
    def ws_candidates(self, pill, sub='open', search='', offset=0, limit=None):
        """Candidates on one list. `pill` is a list, or 'idc' with `sub` one of
        open, failed, waiting, not_done."""
        self._check_agent()
        offset, limit = self._page(offset, limit)
        key = 'id_%s' % sub if pill == 'idc' else pill
        domain = self._list_domain(key)
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('phone', 'ilike', term)]
        order = 'id_check_at desc, id desc' if key in ID_LISTS else 'last_active_at desc, id desc'
        rows = []
        for candidate in self.env['chat2work.candidate'].search(domain, order=order, offset=offset, limit=limit):
            row = self._candidate_row(candidate)
            line = self._list_line(key, candidate)
            row.update(line=line['reason'], line_at=line['when'], line_tag=line['tag'])
            rows.append(row)
        return rows

    # ── ID check, on the candidate's information card ────────────────────────

    def _check_row(self, check):
        return {
            'id': check.id,
            'state': check.state,
            'state_label': self._label(check, 'state') or _("Not finished"),
            'mode': check.mode,
            'at': _dt(check.create_date),
        }

    def _id_check_card(self, candidate):
        """The latest result, whether a check can be run now, and the credits."""
        account = self.env['chat2work.verify.account']._get()
        service = self.env.ref('chat2work_verify.service_said').sudo()
        checks = candidate.id_check_ids.sorted('id', reverse=True)
        latest = checks[:1]
        state = candidate.id_check_state
        line = self._list_line('id_open', candidate)
        if state == 'verified':
            tag, reason = ['ok', _("Verified")], _("Home Affairs confirmed this ID.")
        elif state == 'not_valid':
            tag = line['tag']
            reason = _("%s. Check the ID number with them, correct it, then run the check again.", line['reason'])
        elif state == 'failed':
            tag, reason = line['tag'], _("%s. It isn't charged twice.", line['reason'].rstrip('.'))
        elif not candidate.has_id_number:
            tag, reason = ['plain', _("Not done")], _("No ID number on this candidate yet.")
        else:
            tag, reason = ['plain', _("Not done")], _("No ID check has been run.")
        # A paid check is final; only one that didn't complete (or a new ID number) can be run again.
        can_run = candidate.has_id_number and (account.mode == 'sandbox' or state in ('none', 'failed'))
        return {
            'state': state,
            'tag': tag,
            'reason': reason,
            'at': _dt(candidate.id_check_at),
            'has_id_number': candidate.has_id_number,
            'id_number': candidate.id_number_masked or '',
            'can_run': bool(can_run),
            'again': bool(checks),
            'mode': account.mode,
            'cost': service.credits if account.mode == 'production' else 0,
            'details': {
                'first_names': latest.first_names or '',
                'last_name': latest.last_name or '',
                'dob': fields.Date.to_string(latest.dob) if latest.dob else '',
                'citizenship': latest.citizenship or '',
                'id_status': latest.id_status or '',
                'error': latest.error or '',
                'run_by': latest.user_id.name or '',
                'credits_used': latest.credits_used,
                'mode': latest.mode,
            } if latest else False,
            'history': [self._check_row(check) for check in checks],
            'account': {
                'id': account.id,
                'credits': account.available_credits,
                'used_month': account.credits_used_month,
                'checks_total': account.checks_total,
                'is_low': account.is_low,
                'balance_at': _dt(account.balance_at),
            },
        }
