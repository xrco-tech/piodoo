# -*- coding: utf-8 -*-
"""My queue and Team queues: where queued calls come from, who gets them,
what an outcome does, and who may see what. Nothing here places a call."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,contact_centre.group_contact_centre_agent'
        cls.lindi = new_test_user(cls.env, 'ccq_lindi', name='Lindi Queue', groups=groups)
        cls.kagiso = new_test_user(cls.env, 'ccq_kagiso', name='Kagiso Queue', groups=groups)
        cls.lead = new_test_user(cls.env, 'ccq_lead', name='Thabo Lead',
                                 groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.outsider = new_test_user(cls.env, 'ccq_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace']
        cls.Queue = cls.env['contact.centre.queue.item']
        # Whatever the database already had is not part of these tests.
        cls.Queue.search([]).unlink()
        cls.env['comm.dialer.campaign'].search([('state', '=', 'running')]).write({'state': 'paused'})
        cls.env['res.users'].search([('cc_queue_ready', '=', True)]).write({'cc_queue_ready': False})
        # Calls the database already had are older than this, so they stay out.
        cls.Queue._set_param('since', fields.Datetime.to_string(fields.Datetime.now()))
        cls.Queue._set_param('assign', 'manual')
        if 'chat2work.callback.request' in cls.env:
            cls.env['chat2work.callback.request'].search([]).write({'state': 'done'})
        cls.account = cls.env['comm.voip.account'].search([], limit=1) or cls.env['comm.voip.account'].create(
            {'name': 'Queue test line', 'provider': 'asterisk'})
        cls.sipho = cls.env['res.partner'].create({'name': 'Sipho Dlamini', 'mobile': '27990000511'})

    def _campaign(self, rule='auto', agents=None, numbers=('27990000511', '27990000512'), **vals):
        campaign = self.env['comm.dialer.campaign'].create(dict({
            'name': 'Spring renewals', 'account_id': self.account.id, 'queue_assign': rule,
            'queue_agent_ids': [(6, 0, (agents or self.lindi | self.kagiso).ids)],
        }, **vals))
        for number in numbers:
            self.env['comm.dialer.contact'].create({'campaign_id': campaign.id, 'number': number})
        campaign.action_start()
        return campaign

    def _pull(self):
        self.Queue._queue_pull(force=True)
        return self.Queue.search([('state', '=', 'open')])

    def _item(self, user=None, **vals):
        item = self.Queue.create(dict({'name': 'Nomvula Mokoena', 'phone': '27990000520', 'kind': 'callback'}, **vals))
        if user:
            item._assign(user)
        return item

    # ── Where calls come from ────────────────────────────────────────────
    def test_new_campaign_defaults(self):
        campaign = self.env['comm.dialer.campaign'].create({'name': 'Defaults', 'account_id': self.account.id})
        self.assertEqual(campaign.mode, 'preview', "the agent clicks to call unless the campaign says otherwise")
        self.assertEqual(campaign.queue_assign, 'auto')

    def test_running_campaign_rows_are_queued_once(self):
        self._campaign(rule='manual')
        items = self._pull()
        self.assertEqual(len(items), 2)
        self.assertEqual(set(items.mapped('kind')), {'campaign'})
        self.assertEqual(items.filtered(lambda i: i.phone == '27990000511').name, 'Sipho Dlamini')
        self.assertEqual(len(self._pull()), 2, "pulling again must not queue the same rows twice")

    def test_campaign_that_is_not_running_queues_nothing(self):
        campaign = self._campaign(rule='manual')
        campaign.action_pause()
        self.assertFalse(self._pull())

    def test_finished_row_leaves_the_queue(self):
        campaign = self._campaign(rule='manual', numbers=('27990000511',))
        item = self._pull()
        campaign.contact_ids.register_result('contacted')
        self._pull()
        self.assertEqual((item.state, item.outcome), ('done', 'done'))

    def test_missed_call_is_queued_and_a_second_one_is_noted(self):
        Call = self.env['comm.voip.call']
        vals = {'direction': 'incoming', 'state': 'no_answer', 'from_number': '27990000530', 'to_number': '27100000000'}
        Call.create(dict(vals, start_time=fields.Datetime.now() + timedelta(seconds=1)))
        item = self._pull()
        self.assertEqual((item.kind, item.phone), ('missed', '27990000530'))
        Call.create(dict(vals, start_time=fields.Datetime.now() + timedelta(seconds=2)))
        self.assertEqual(self._pull(), item, "one person is owed one call, however often they rang")
        self.assertIn('Rang again', item.log)

    def test_missed_call_from_before_install_is_left_alone(self):
        self.env['comm.voip.call'].create({
            'direction': 'incoming', 'state': 'no_answer', 'from_number': '27990000531', 'to_number': '27100000000',
            'start_time': fields.Datetime.now() - timedelta(hours=5)})
        self.assertFalse(self._pull())

    def test_callback_outcome_on_a_call_goes_to_that_agent(self):
        callback = self.env['comm.disposition'].create({'name': 'Call me back', 'category': 'callback'})
        self.env['whatsapp.call.log'].create({
            'call_id': 'ccq_cb_1', 'call_direction': 'incoming', 'call_status': 'ended', 'duration': 40,
            'call_timestamp': fields.Datetime.now(), 'from_number': '27990000540', 'to_number': '27100000000',
            'agent_user_id': self.kagiso.id, 'disposition_id': callback.id, 'disposition_note': 'After 3pm'})
        # The call's write time is when this test's transaction began, before setUpClass set "since".
        self.Queue._set_param('since', fields.Datetime.to_string(fields.Datetime.now() - timedelta(hours=1)))
        item = self._pull().filtered(lambda i: i.phone == '27990000540')
        self.assertEqual((item.kind, item.user_id, item.note), ('callback', self.kagiso, 'After 3pm'))

    def test_chat2work_callback_is_queued_and_closed_with_it(self):
        if 'chat2work.callback.request' not in self.env:
            self.skipTest("Chat2Work is not installed")
        request = self.env['chat2work.callback.request'].create({'phone': '27990000550', 'channel': 'ussd'})
        item = self._pull()
        self.assertEqual((item.kind, item.origin, item.c2w_callback_id), ('callback', 'Chat2Work', request.id))
        item._assign(self.lindi)
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'done')
        self.assertEqual(request.state, 'done')

    # ── Who gets them ────────────────────────────────────────────────────
    def test_auto_shares_between_ready_agents_only(self):
        self.lindi.cc_queue_ready = True
        self._campaign(rule='auto', numbers=('27990000511', '27990000512', '27990000513'))
        items = self._pull()
        self.assertEqual(items.mapped('user_id'), self.lindi, "Kagiso is not ready, so gets nothing")

    def test_auto_gives_to_whoever_has_fewest(self):
        self.lindi.cc_queue_ready = self.kagiso.cc_queue_ready = True
        self._item(self.lindi)
        self._item(self.lindi, phone='27990000521')
        self._campaign(rule='auto')
        items = self._pull().filtered(lambda i: i.kind == 'campaign')
        self.assertEqual(items.mapped('user_id'), self.kagiso)

    def test_auto_waits_until_someone_is_ready(self):
        self._campaign(rule='auto', agents=self.lindi)
        self.assertFalse(self._pull().mapped('user_id'))
        self.Ws.with_user(self.lindi).ws_queue_ready(True)
        self.assertEqual(self.Queue.search([('state', '=', 'open')]).mapped('user_id'), self.lindi)

    def test_manual_stays_unassigned(self):
        self.lindi.cc_queue_ready = True
        self._campaign(rule='manual')
        self.assertFalse(self._pull().mapped('user_id'))

    def test_pool_take_the_next_one(self):
        self._campaign(rule='pool', agents=self.lindi)
        self._pull()
        mine = self.Ws.with_user(self.lindi).ws_queue()
        self.assertEqual((mine['pool'], mine['counts']['all']), (2, 0))
        self.assertEqual(self.Ws.with_user(self.kagiso).ws_queue()['pool'], 0, "Kagiso is not on this campaign")
        taken = self.Ws.with_user(self.lindi).ws_queue_take()
        self.assertEqual(self.Queue.browse(taken).user_id, self.lindi)
        self.assertEqual(self.Ws.with_user(self.lindi).ws_queue()['pool'], 1)
        with self.assertRaises(UserError):
            self.Ws.with_user(self.kagiso).ws_queue_take()

    def test_calls_outside_a_campaign_follow_the_setting(self):
        self.lindi.cc_queue_ready = True
        item = self._item()
        self.Ws.with_user(self.lead).ws_team_rule('auto')
        self.assertEqual(item.user_id, self.lindi)
        with self.assertRaises(AccessError):
            self.Ws.with_user(self.lindi).ws_team_rule('pool')

    # ── My queue ─────────────────────────────────────────────────────────
    def test_my_queue_lists_only_mine_in_due_order(self):
        now = fields.Datetime.now()
        late = self._item(self.lindi, due_at=now - timedelta(minutes=40), timed=True)
        soon = self._item(self.lindi, phone='27990000521', kind='follow', due_at=now + timedelta(days=2), timed=True)
        self._item(self.kagiso, phone='27990000522')
        result = self.Ws.with_user(self.lindi).ws_queue()
        self.assertEqual([row['id'] for row in result['rows']], [late.id, soon.id])
        self.assertEqual([row['group'] for row in result['rows']], ['overdue', 'later'])
        self.assertEqual(result['rows'][0]['late'], 40)
        self.assertEqual((result['counts']['all'], result['counts']['callback'], result['overdue']), (2, 1, 1))
        self.assertEqual(len(self.Ws.with_user(self.lindi).ws_queue(pill='follow')['rows']), 1)
        self.assertEqual(self.Ws.with_user(self.lindi).ws_counts()['queue'], 2)

    def test_campaign_call_with_no_set_time_is_never_overdue(self):
        self._campaign(rule='manual', numbers=('27990000511',))
        item = self._pull()
        item.due_at = fields.Datetime.now() - timedelta(hours=6)
        item._assign(self.lindi)
        self.assertEqual(self.Ws.with_user(self.lindi).ws_queue()['rows'][0]['group'], 'now')

    def test_someone_elses_call_cannot_be_opened_or_closed(self):
        item = self._item(self.kagiso)
        Ws = self.Ws.with_user(self.lindi)
        with self.assertRaises(AccessError):
            Ws.ws_queue_item(item.id)
        with self.assertRaises(AccessError):
            Ws.ws_queue_outcome(item.id, 'done')
        self.assertTrue(self.Ws.with_user(self.lead).ws_queue_item(item.id)['id'])
        with self.assertRaises(AccessError):
            self.Ws.with_user(self.outsider).ws_queue()

    def test_one_call_says_why(self):
        item = self._item(note='Debit order date, mornings only', origin='WhatsApp')
        item._assign(self.lindi, by=self.lead)
        data = self.Ws.with_user(self.lindi).ws_queue_item(item.id)
        self.assertEqual((data['full_note'], data['assigned_by'], data['mine']),
                         ('Debit order date, mornings only', 'Thabo Lead', True))
        self.assertFalse(data['wa'], "nobody has allowed WhatsApp calls from this number")

    # ── After the call ───────────────────────────────────────────────────
    def test_done_closes_the_call_and_the_campaign_row(self):
        campaign = self._campaign(rule='manual', numbers=('27990000511',))
        item = self._pull()
        item._assign(self.lindi)
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'done', note='Renewed for a year')
        self.assertEqual((item.state, item.outcome, item.done_by_id), ('done', 'done', self.lindi))
        self.assertIn('Renewed for a year', item.log)
        self.assertEqual(campaign.contact_ids.state, 'contacted')
        self.assertEqual(self.Ws.with_user(self.lindi).ws_queue()['done'], 1)
        with self.assertRaises(UserError):
            self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'done')

    def test_no_answer_retries_then_gives_up(self):
        item = self._item(self.lindi, max_attempts=2)
        Ws = self.Ws.with_user(self.lindi)
        Ws.ws_queue_outcome(item.id, 'no_answer')
        self.assertEqual((item.state, item.attempts, item.timed), ('open', 1, True))
        self.assertGreater(item.due_at, fields.Datetime.now() + timedelta(minutes=90))
        Ws.ws_queue_outcome(item.id, 'no_answer')
        self.assertEqual((item.state, item.outcome), ('done', 'gave_up'))

    def test_no_answer_on_a_campaign_row_follows_the_campaign(self):
        campaign = self._campaign(rule='manual', numbers=('27990000511',), max_attempts=2, retry_gap_hours=6)
        item = self._pull()
        item._assign(self.lindi)
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'no_answer')
        row = campaign.contact_ids
        self.assertEqual((row.state, row.attempts, item.attempts), ('retry', 1, 1))
        self.assertEqual(item.due_at, row.next_attempt)
        self._pull()
        self.assertEqual(item.state, 'open')
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'no_answer')
        self.assertEqual((row.state, item.outcome), ('failed', 'gave_up'))

    def test_call_back_at_a_set_time(self):
        item = self._item(self.lindi)
        Ws = self.Ws.with_user(self.lindi)
        with self.assertRaises(UserError):
            Ws.ws_queue_outcome(item.id, 'later', when=fields.Datetime.to_string(fields.Datetime.now() - timedelta(hours=1)))
        due = fields.Datetime.now().replace(microsecond=0) + timedelta(days=1)
        Ws.ws_queue_outcome(item.id, 'later', when=fields.Datetime.to_string(due))
        self.assertEqual((item.due_at, item.timed, item.state), (due, True, 'open'))

    def test_hand_to_someone_else(self):
        item = self._item(self.lindi)
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'hand', user_id=self.kagiso.id)
        self.assertEqual((item.user_id, item.assigned_by_id), (self.kagiso, self.lindi))
        with self.assertRaises(UserError):
            self.Ws.with_user(self.kagiso).ws_queue_outcome(item.id, 'hand', user_id=self.outsider.id)

    def test_do_not_call_again(self):
        item = self._item(self.lindi, phone='27990000560')
        self.Ws.with_user(self.lindi).ws_queue_outcome(item.id, 'dnc')
        self.assertEqual(item.outcome, 'dnc')
        self.assertTrue(self.env['comm.dialer.dnc'].search_count([('number', '=', '27990000560')]))

    def test_follow_up_goes_to_whoever_set_it(self):
        partner = self.env['res.partner'].create({'name': 'Thandeka Mthembu', 'mobile': '27990000570'})
        contact = self.env['contact.centre.contact'].create({'partner_id': partner.id, 'phone_number': '27990000570'})
        Ws = self.Ws.with_user(self.lindi)
        self.assertEqual([p['id'] for p in Ws.ws_queue_people('27990000570')], [contact.id])
        due = fields.Datetime.to_string(fields.Datetime.now() + timedelta(hours=3))
        item = self.Queue.browse(Ws.ws_queue_follow_up(contact.id, due, note='Check the documents arrived'))
        self.assertEqual((item.kind, item.user_id, item.contact_id, item.timed), ('follow', self.lindi, contact, True))
        with self.assertRaises(UserError):
            Ws.ws_queue_follow_up(contact.id, False)

    # ── Team queues ──────────────────────────────────────────────────────
    def test_team_view_is_for_managers(self):
        with self.assertRaises(AccessError):
            self.Ws.with_user(self.lindi).ws_team()
        with self.assertRaises(AccessError):
            self.Ws.with_user(self.lindi).ws_team_assign([1], self.lindi.id)
        self.assertFalse(self.Ws.with_user(self.lindi).ws_boot()['lead'])
        self.assertTrue(self.Ws.with_user(self.lead).ws_boot()['lead'])

    def test_team_view_counts_and_assigns(self):
        now = fields.Datetime.now()
        waiting = self._item(due_at=now - timedelta(hours=2))
        other = self._item(phone='27990000521')
        self._item(self.lindi, phone='27990000522')
        Ws = self.Ws.with_user(self.lead)
        data = Ws.ws_team()
        self.assertEqual((data['tiles']['waiting'], data['tiles']['unassigned'], data['tiles']['overdue']), (3, 2, 1))
        self.assertEqual([row['id'] for row in data['rows']], [waiting.id, other.id])
        people = {p['id']: p for p in data['people']}
        self.assertEqual((people[False]['todo'], people[self.lindi.id]['todo']), (2, 1))
        self.assertEqual(Ws.ws_counts()['unassigned'], 2)

        Ws.ws_team_assign([waiting.id], self.kagiso.id)
        self.assertEqual((waiting.user_id, waiting.assigned_by_id), (self.kagiso, self.lead))
        self.assertEqual([row['id'] for row in Ws.ws_team(user_id=self.kagiso.id)['rows']], [waiting.id])
        Ws.ws_team_assign([waiting.id], False)
        self.assertFalse(waiting.user_id)

    def test_share_out_evenly(self):
        for number in range(4):
            self._item(phone='2799000058%s' % number)
        campaign = self._campaign(rule='manual', agents=self.kagiso, numbers=('27990000511',))
        self._pull()
        shared = self.Ws.with_user(self.lead).ws_team_share()
        self.assertEqual(shared, 5)
        items = self.Queue.search([('state', '=', 'open')])
        self.assertFalse(items.filtered(lambda i: not i.user_id))
        self.assertEqual(items.filtered('dialer_contact_id').user_id, self.kagiso, "a campaign's calls stay with its agents")
        self.assertTrue(campaign)
