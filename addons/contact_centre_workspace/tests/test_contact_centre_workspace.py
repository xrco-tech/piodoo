# -*- coding: utf-8 -*-
"""What the Contact Centre workspace reads: the list, what counts as unread,
one conversation, and who may use it. Nothing here sends a message."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspace(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_agent', groups='contact_centre.group_contact_centre_agent')
        cls.outsider = new_test_user(cls.env, 'ccw_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        # Whatever the database already holds is not this test's business.
        cls.env['contact.centre.contact'].search([]).write({'state': 'resolved'})
        cls.nokuthula = cls._contact('Nokuthula Mabena', '27990000142')
        cls.themba = cls._contact('Themba Khoza', '27990000188')
        cls.count = 0

    @classmethod
    def _contact(cls, name, mobile):
        partner = cls.env['res.partner'].create({'name': name, 'mobile': mobile})
        return cls.env['contact.centre.contact'].create({'partner_id': partner.id})

    def _msg(self, contact, body, channel='whatsapp', out=False, minutes_ago=0, **vals):
        return self.env['contact.centre.message'].create(dict({
            'contact_id': contact.id, 'channel': channel, 'direction': 'outbound' if out else 'inbound',
            'body_text': body, 'status': 'sent' if out else 'delivered',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _wa(self, wa_id, body, incoming=True, minutes_ago=0):
        type(self).count += 1
        return self.env['whatsapp.message'].create({
            'message_id': 'wamid.ccw_%s' % self.count, 'wa_id': wa_id, 'is_incoming': incoming,
            'message_type': 'text', 'message_body': body,
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)})

    def _ids(self, **kwargs):
        """The listed conversations, leaving out any the database already had."""
        ours = (self.nokuthula | self.themba).ids
        return [r['id'] for r in self.Ws.ws_list(**kwargs)['rows'] if r['id'] in ours]

    def _row(self, contact, **kwargs):
        rows = {r['id']: r for r in self.Ws.ws_list(**kwargs)['rows']}
        return rows.get(contact.id)

    def test_agents_only(self):
        Outsider = self.env['contact.centre.workspace'].with_user(self.outsider)
        for call in (Outsider.ws_boot, Outsider.ws_counts, Outsider.ws_list,
                     lambda: Outsider.ws_thread(self.nokuthula.id),
                     lambda: Outsider.ws_set_state(self.nokuthula.id, 'pending'),
                     lambda: Outsider.ws_ai_refresh(self.nokuthula.id)):
            with self.assertRaises(AccessError):
                call()

    def test_boot(self):
        boot = self.Ws.ws_boot()
        self.assertEqual(boot['counts'], {'unread': 0})
        self.assertTrue(boot['me']['initials'])
        keys = [entry['key'] for entry in boot['rail']]
        self.assertIn('campaigns', keys)
        # Calls and Contacts are sections of the workspace now.
        self.assertFalse({'calls', 'contacts'} & set(keys))
        for entry in boot['rail']:
            self.assertTrue(self.env['ir.actions.actions'].browse(entry['action']).exists())

    def test_list_rows_filters_and_search(self):
        self._msg(self.nokuthula, 'I was told my cover lapsed', minutes_ago=30)
        self._msg(self.nokuthula, 'Why?\nPlease   sort this out', minutes_ago=12)
        self._msg(self.themba, 'We sent the form', channel='sms', out=True, minutes_ago=5)

        self.assertEqual(self._ids(), [self.themba.id, self.nokuthula.id])   # newest first
        row = self._row(self.nokuthula)
        self.assertEqual((row['name'], row['initials'], row['channel'], row['out'], row['unread']),
                         ('Nokuthula Mabena', 'NM', 'whatsapp', False, 2))
        self.assertEqual(row['preview'], 'Why? Please sort this out')
        row = self._row(self.themba)
        self.assertEqual((row['channel'], row['out'], row['unread']), ('sms', True, 0))

        self.assertEqual(self._ids(pill='unread'), [self.nokuthula.id])
        self.assertEqual(self._ids(pill='sms'), [self.themba.id])
        self.assertEqual(self._ids(pill='open'), [self.themba.id, self.nokuthula.id])
        self.assertFalse(self._ids(pill='pending'))
        self.assertEqual([r['id'] for r in self.Ws.ws_list(search='990000142')['rows']], [self.nokuthula.id])
        self.assertEqual([r['id'] for r in self.Ws.ws_list(search='themba')['rows']], [self.themba.id])
        self.assertEqual(self.Ws.ws_counts(), {'unread': 1})

        page = self.Ws.ws_list(limit=1, search='27990000')
        self.assertEqual((len(page['rows']), page['more']), (1, True))
        self.assertEqual(self.Ws.ws_list(limit=1, offset=1, search='27990000')['rows'][0]['id'], self.nokuthula.id)

    def test_number_only_contact(self):
        stranger = self._contact('WhatsApp 27990000199', '27990000199')
        self._msg(stranger, 'Hi')
        self.assertEqual(self._row(stranger)['initials'], '#')

    def test_what_counts_as_unread(self):
        # A call is answered or missed, not replied to.
        self._msg(self.nokuthula, 'Missed call', channel='voice', minutes_ago=50)
        self.assertEqual(self._row(self.nokuthula)['unread'], 0)

        self._msg(self.nokuthula, 'Hello?', minutes_ago=40)
        self.assertEqual(self._row(self.nokuthula)['unread'], 1)
        # A reply that failed to send does not end the wait.
        self._msg(self.nokuthula, 'Hi Nokuthula', out=True, minutes_ago=38, status='failed')
        self.assertEqual(self._row(self.nokuthula)['unread'], 1)
        # Our reply ends the wait.
        self._msg(self.nokuthula, 'Hi Nokuthula', out=True, minutes_ago=35)
        self.assertEqual(self._row(self.nokuthula)['unread'], 0)

        # So does the bot's: it answers on WhatsApp without the thread getting a copy.
        incoming = self._wa('27990000142', 'Menu please', minutes_ago=30)
        self._msg(self.nokuthula, 'Menu please', minutes_ago=30, whatsapp_message_id=incoming.id,
                  provider_message_id=incoming.message_id)
        self.assertEqual(self._row(self.nokuthula)['unread'], 1)
        self._wa('27990000142', '1. Balance  2. Agent', incoming=False, minutes_ago=29)
        self.assertEqual(self._row(self.nokuthula)['unread'], 0)

        # And so does an agent opening it, for every agent.
        self._msg(self.nokuthula, 'Agent please', minutes_ago=20)
        self.assertEqual(self.Ws.ws_counts(), {'unread': 1})
        thread = self.Ws.ws_thread(self.nokuthula.id)
        self.assertEqual(thread['waiting'], 1)
        self.assertTrue(thread['waiting_since'])
        self.assertEqual(self.Ws.ws_counts(), {'unread': 0})
        # Seen is not answered: the thread still says how long they have waited.
        self.assertEqual(self.Ws.ws_thread(self.nokuthula.id)['waiting'], 1)
        self._msg(self.nokuthula, 'Calling you now', out=True, minutes_ago=1)
        self.assertEqual(self.Ws.ws_thread(self.nokuthula.id)['waiting'], 0)

        # A resolved conversation is never unread; a new message while it is open again is.
        self._msg(self.nokuthula, 'Thanks', minutes_ago=-1)
        self.assertEqual(self._row(self.nokuthula)['unread'], 1)
        self.Ws.ws_set_state(self.nokuthula.id, 'resolved')
        self.assertEqual(self._row(self.nokuthula)['unread'], 0)

    def test_thread(self):
        incoming = self._wa('27990000142', 'Hi', minutes_ago=60 * 30)
        self._msg(self.nokuthula, 'Hi', minutes_ago=60 * 30, whatsapp_message_id=incoming.id,
                  provider_message_id=incoming.message_id)
        self._wa('27990000142', 'Welcome to XR Co.', incoming=False, minutes_ago=60 * 30 - 1)
        # A reply typed in the inbox is in the thread already: it must not show twice.
        typed = self._wa('27990000142', 'An agent will call you', incoming=False, minutes_ago=60 * 29)
        self._msg(self.nokuthula, 'An agent will call you', out=True, minutes_ago=60 * 29,
                  provider_message_id=typed.message_id)
        self._msg(self.nokuthula, 'Outgoing call, 3:12', channel='voice', out=True, minutes_ago=60 * 28)
        self._msg(self.nokuthula, 'Your policy schedule', channel='sms', out=True, minutes_ago=60 * 27,
                  status='failed', failure_reason='No credit')

        thread = self.Ws.ws_thread(self.nokuthula.id, seen=False)
        self.assertEqual(
            [(m['channel'], m['out'], m['auto'], m['body']) for m in thread['messages']],
            [('whatsapp', False, False, 'Hi'),
             ('whatsapp', True, True, 'Welcome to XR Co.'),
             ('whatsapp', True, False, 'An agent will call you'),
             ('voice', True, False, 'Outgoing call, 3:12'),
             ('sms', True, False, 'Your policy schedule')])
        self.assertTrue(thread['messages'][3]['call'])
        self.assertEqual((thread['messages'][4]['status'], thread['messages'][4]['failure']), ('failed', 'No credit'))
        self.assertEqual((thread['name'], thread['phone'], thread['state'], thread['initials']),
                         ('Nokuthula Mabena', '27990000142', 'open', 'NM'))
        self.assertTrue(thread['has_whatsapp'])
        # Their last WhatsApp message is more than 24 hours old: no typed WhatsApp reply.
        self.assertFalse(thread['window_open'])
        self.assertEqual(thread['channel'], 'sms')            # the last channel we can type on
        self.assertFalse(self.nokuthula.ws_seen_at)           # seen=False leaves it unseen
        labels = {d['label']: d['value'] for d in thread['details']}
        self.assertEqual(labels['Channels'], 'SMS, Voice, WhatsApp')

        self._msg(self.nokuthula, 'Are you there?')
        thread = self.Ws.ws_thread(self.nokuthula.id)
        self.assertTrue(thread['window_open'])
        self.assertTrue(self.nokuthula.ws_seen_at)

        with self.assertRaises(UserError):
            self.Ws.ws_thread(0)

    def test_status(self):
        self.Ws.ws_set_state(self.themba.id, 'pending')
        self.assertEqual(self.themba.state, 'pending')
        self.assertEqual(self._row(self.themba, pill='pending')['state'], 'pending')
        with self.assertRaises(UserError):
            self.Ws.ws_set_state(self.themba.id, 'deleted')
