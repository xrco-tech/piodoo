# -*- coding: utf-8 -*-
"""Who is waiting for an agent: what the alert icon is told, the people who
aren't candidates, and the email about anyone left waiting."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

WA = 'odoo.addons.comm_whatsapp.models.whatsapp_message.WhatsAppMessage.send_whatsapp_payload'
STRANGER = '27605550199'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workAlerts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'c2w_alert_agent', groups='chat2work.group_agent')
        cls.outsider = new_test_user(cls.env, 'c2w_alert_outsider', groups='base.group_user')
        cls.boss = new_test_user(cls.env, 'c2w_alert_boss', email='boss@example.com',
                                 groups='chat2work.group_agent,chat2work_workspace.group_waiting_email')
        cls.Ws = cls.env['chat2work.workspace'].with_user(cls.agent)
        Candidate = cls.env['chat2work.candidate']
        cls.thandi = Candidate.create({'name': 'Thandiwe Mokoena', 'phone': '+27825550142', 'whatsapp_opt_in': True})
        cls.nameless = Candidate.create({'name': '+27715550107', 'phone': '+27715550107'})
        # Whatever the database already holds is not this test's business.
        cls.env['ir.config_parameter'].set_param('chat2work.wa_phone_number_id', 'test-number')

    def _log(self, candidate, channel, direction, text, minutes_ago=0):
        candidate._c2w_ucx_log(channel, [{
            'dir': direction, 'text': text, 'at': fields.Datetime.now() - timedelta(minutes=minutes_ago)}])

    def _wa(self, wa_id, body, incoming=True, minutes_ago=0, name='Sipho', **vals):
        self.count = getattr(self, 'count', 0) + 1
        return self.env['whatsapp.message'].create(dict({
            'message_id': 'wamid.alert_%s' % self.count, 'wa_id': wa_id, 'is_incoming': incoming,
            'message_type': 'text', 'message_body': body, 'contact_name': name if incoming else wa_id,
            'phone_number_id': 'test-number',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _kinds(self):
        return sorted(item['kind'] for item in self.Ws.ws_alerts()['items'])

    def test_agents_only(self):
        Outsider = self.env['chat2work.workspace'].with_user(self.outsider)
        for call in (Outsider.ws_alerts, Outsider.ws_unknown, lambda: Outsider.ws_unknown_thread(STRANGER),
                     lambda: Outsider.ws_unknown_send(STRANGER, 'Hi'), lambda: Outsider.ws_unknown_done(STRANGER)):
            with self.assertRaises(AccessError):
                call()

    def test_alerts_list_who_is_waiting(self):
        self.assertEqual(self.Ws.ws_alerts()['count'], 0)
        self._log(self.thandi, 'whatsapp', 'inbound', 'Please call me', minutes_ago=5)
        self.env['chat2work.callback.request'].create(
            {'candidate_id': self.nameless.id, 'phone': self.nameless.phone, 'channel': 'ussd'})
        self._wa(STRANGER, "'Ispani", minutes_ago=2)

        alerts = self.Ws.ws_alerts()
        self.assertEqual(alerts['counts'], {'reply': 1, 'callback': 1, 'unknown': 1})
        self.assertEqual(alerts['count'], 3)
        by_kind = {item['kind']: item for item in alerts['items']}
        self.assertEqual(by_kind['reply']['candidate_id'], self.thandi.id)
        self.assertEqual(by_kind['reply']['name'], 'Thandiwe Mokoena')
        self.assertEqual(by_kind['unknown']['wa_id'], STRANGER)
        self.assertEqual(by_kind['unknown']['name'], 'Sipho')
        self.assertEqual(by_kind['callback']['candidate_id'], self.nameless.id)

        # A second message from the same person is a new alert; an answer ends the wait.
        first = by_kind['reply']['key']
        self._log(self.thandi, 'whatsapp', 'inbound', 'Hello?')
        second = [item['key'] for item in self.Ws.ws_alerts()['items'] if item['kind'] == 'reply']
        self.assertEqual(len(second), 1)
        self.assertNotEqual(second[0], first)
        self._log(self.thandi, 'whatsapp', 'outbound', 'Calling you now')
        self.assertEqual(self._kinds(), ['callback', 'unknown'])

    def test_old_waits_count_but_do_not_alert(self):
        self._log(self.thandi, 'whatsapp', 'inbound', 'Anyone there?', minutes_ago=60 * 30)
        alerts = self.Ws.ws_alerts()
        self.assertEqual(alerts['counts']['reply'], 1)
        self.assertFalse(alerts['items'])

    def test_not_candidates_list(self):
        self._wa(STRANGER, 'Hi', minutes_ago=30)
        self._wa(STRANGER, 'Welcome to Chat2Work', incoming=False, minutes_ago=29)
        self._wa('27825550142', 'From a candidate', name='Thandi')         # a candidate: not on this list
        self._wa('27600000001', 'Other line', phone_number_id='another')   # another WhatsApp number's traffic
        self._wa('27600000002', 'Long ago', minutes_ago=60 * 24 * 20)
        self._wa('27600000003', '', message_type='reaction')

        rows = self.Ws.ws_unknown()
        self.assertEqual([r['id'] for r in rows], [STRANGER])
        self.assertFalse(rows[0]['needs_reply'])           # the bot answered last
        self.assertTrue(rows[0]['preview_out'])
        self.assertEqual(self.Ws.ws_counts()['unknown'], 0)

        self._wa(STRANGER, 'Still waiting')
        row = self.Ws.ws_unknown()[0]
        self.assertTrue(row['needs_reply'])
        self.assertEqual((row['name'], row['phone'], row['preview']), ('Sipho', '+' + STRANGER, 'Still waiting'))
        self.assertEqual(self.Ws.ws_counts()['unknown'], 1)
        self.assertEqual([r['id'] for r in self.Ws.ws_unknown('sipho')], [STRANGER])
        self.assertFalse(self.Ws.ws_unknown('nobody'))

        thread = self.Ws.ws_unknown_thread(STRANGER)
        self.assertEqual([(m['dir'], m['body']) for m in thread['timeline']],
                         [('inbound', 'Hi'), ('outbound', 'Welcome to Chat2Work'), ('inbound', 'Still waiting')])
        self.assertTrue(thread['window_open'])
        self.assertEqual(thread['received'], 2)
        self.assertFalse(self.Ws.ws_unknown_thread('27825550142'))

    def test_dealt_with_until_they_write_again(self):
        self._wa(STRANGER, 'Hi', minutes_ago=3)
        self.assertEqual(self._kinds(), ['unknown'])
        self.Ws.ws_unknown_done(STRANGER)
        self.assertFalse(self._kinds())
        self.assertFalse(self.Ws.ws_unknown()[0]['needs_reply'])
        self._wa(STRANGER, 'Me again', minutes_ago=-1)
        self.assertEqual(self._kinds(), ['unknown'])
        self.Ws.ws_unknown_done(STRANGER)                  # a second time reuses the same record
        self.assertEqual(self.env['chat2work.workspace.handled'].search_count([('wa_id', '=', STRANGER)]), 1)

    def test_reply_to_someone_who_is_not_a_candidate(self):
        self._wa(STRANGER, 'Hi', minutes_ago=5)

        def sent(recipient, content, **kwargs):
            self._wa(recipient, content['text']['body'], incoming=False)
            return {'success': True, 'message_id': 'wamid.reply'}

        with patch(WA, side_effect=sent) as send:
            thread = self.Ws.ws_unknown_send(STRANGER, '  Hello Sipho, how can we help?  ')
        self.assertEqual(send.call_args.args[:2],
                         (STRANGER, {'type': 'text', 'text': {'body': 'Hello Sipho, how can we help?'}}))
        self.assertEqual(thread['timeline'][-1]['dir'], 'outbound')
        self.assertFalse(thread['needs_reply'])

        with patch(WA, return_value={'success': False, 'error': 'Payment issue'}):
            with self.assertRaisesRegex(UserError, 'Payment issue'):
                self.Ws.ws_unknown_send(STRANGER, 'Again')

        # Past WhatsApp's 24 hours nothing is sent.
        old = '27605550188'
        self._wa(old, 'Hi', minutes_ago=60 * 30)
        with patch(WA) as send:
            with self.assertRaises(UserError):
                self.Ws.ws_unknown_send(old, 'Too late')
        send.assert_not_called()

    def test_incoming_whatsapp_tells_open_screens(self):
        with patch('odoo.addons.bus.models.bus.ImBus._sendone') as sendone:
            self._wa(STRANGER, 'Hi')
            self.assertEqual([c.args for c in sendone.call_args_list],
                             [('chat2work_workspace', 'chat2work_workspace/changed', {'what': 'whatsapp'})])
            self._wa(STRANGER, 'Sent by us', incoming=False)
            self.assertEqual(sendone.call_count, 1)

    def test_email_once_for_each_long_wait(self):
        Ws = self.env['chat2work.workspace']
        Param = self.env['ir.config_parameter']
        last = 'chat2work_workspace.waiting_email_last'
        self._log(self.thandi, 'whatsapp', 'inbound', 'Please call me', minutes_ago=17)
        self._log(self.nameless, 'sms', 'inbound', 'Help', minutes_ago=17)
        self._wa(STRANGER, 'Hi', minutes_ago=16)
        self._wa('27605550188', 'Just now', minutes_ago=2)                 # hasn't waited long enough yet
        self._log(self.thandi, 'ussd', 'inbound', 'USSD session', minutes_ago=1)   # not something to answer

        mail = Ws._cron_waiting_email()
        self.assertEqual(mail.email_to, self.boss.email_formatted)
        self.assertIn('3 waiting', mail.subject)
        body = str(mail.body_html)
        self.assertIn('Thandiwe', body)
        self.assertIn('more than 15 minutes', body)
        self.assertIn('number ending 0199', body)
        # No phone numbers leave in an email: a candidate saved under their number is "A candidate".
        self.assertIn('A candidate', body)
        self.assertNotIn('5550', body)
        self.assertIn('/odoo/action-chat2work_workspace.action_chat2work_workspace', body)

        # The same waits are not emailed again on the next run.
        self.assertFalse(Ws._cron_waiting_email())
        # The newer one is, once it has waited long enough.
        Param.set_param(last, fields.Datetime.to_string(fields.Datetime.now() - timedelta(minutes=1)))
        self.env['whatsapp.message'].search([('wa_id', '=', '27605550188')]).message_timestamp = \
            fields.Datetime.now() - timedelta(minutes=15, seconds=30)
        mail = Ws._cron_waiting_email()
        self.assertIn('1 waiting', mail.subject)
        self.assertIn('number ending 0188', str(mail.body_html))

    def test_email_off_or_nobody_to_tell(self):
        Ws = self.env['chat2work.workspace']
        Param = self.env['ir.config_parameter']
        last = 'chat2work_workspace.waiting_email_last'
        self._log(self.thandi, 'whatsapp', 'inbound', 'Please call me', minutes_ago=17)
        Param.set_param('chat2work_workspace.waiting_email_minutes', '0')
        self.assertFalse(Ws._cron_waiting_email())
        Param.set_param('chat2work_workspace.waiting_email_minutes', '15')
        Param.set_param(last, False)
        self.env.ref('chat2work_workspace.group_waiting_email').users = False
        self.assertFalse(Ws._cron_waiting_email())
