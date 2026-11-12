# -*- coding: utf-8 -*-
"""The Campaigns section of the workspace: the list and its filters, one
campaign, and who may start or stop it. Starting a campaign here only marks
it as running: the scheduled job does the sending, and never runs in a test."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceCampaigns(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_camp_agent', groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.manager = new_test_user(cls.env, 'ccw_camp_manager', groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.outsider = new_test_user(cls.env, 'ccw_camp_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.Boss = cls.env['contact.centre.workspace'].with_user(cls.manager)
        cls.template = cls.env['contact.centre.template'].create({
            'name': 'Zzq renewal reminder', 'channel': 'whatsapp', 'body_text': 'Your cover renews on the 1st.'})
        cls.people = cls.env['contact.centre.contact']
        for name, mobile in (('Zzq Anele', '27990000511'), ('Zzq Bongani', '27990000522'), ('Zzq Cebo', '27990000533')):
            partner = cls.env['res.partner'].create({'name': name, 'mobile': mobile})
            cls.people |= cls.env['contact.centre.contact'].create({'partner_id': partner.id})
        cls.renewals = cls._campaign('Zzq Renewals', template_id=cls.template.id, contact_ids=[(6, 0, cls.people.ids)])
        cls.helpdesk = cls._campaign('Zzq Help desk', campaign_type='inbound', channel='both')

    @classmethod
    def _campaign(cls, name, **vals):
        return cls.env['contact.centre.campaign'].create(dict(
            {'name': name, 'campaign_type': 'outbound', 'channel': 'whatsapp'}, **vals))

    def _msg(self, contact, campaign, status='sent', minutes_ago=0, out=True, **vals):
        return self.env['contact.centre.message'].create(dict({
            'contact_id': contact.id, 'campaign_id': campaign.id, 'channel': 'whatsapp',
            'direction': 'outbound' if out else 'inbound', 'body_text': 'Your cover renews on the 1st.', 'status': status,
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _ids(self, ws=None, **kwargs):
        kwargs.setdefault('search', 'zzq')
        return [row['id'] for row in (ws or self.Ws).ws_campaigns(**kwargs)['rows']]

    def test_agents_only(self):
        Outsider = self.env['contact.centre.workspace'].with_user(self.outsider)
        for attempt in (Outsider.ws_campaigns, lambda: Outsider.ws_campaign(self.renewals.id),
                        lambda: Outsider.ws_campaign_action(self.renewals.id, 'start')):
            with self.assertRaises(AccessError):
                attempt()

    def test_list(self):
        old = self._campaign('Zzq Winter drive', state='done')
        self.helpdesk.state = 'running'
        # What is running comes first, then drafts, then what is over.
        self.assertEqual(self._ids(), [self.helpdesk.id, self.renewals.id, old.id])
        result = self.Ws.ws_campaigns(search='zzq')
        self.assertEqual((result['total'], result['more'], result['can_manage']), (3, False, False))
        self.assertTrue(self.Boss.ws_campaigns(search='zzq')['can_manage'])
        row = {r['id']: r for r in result['rows']}[self.renewals.id]
        self.assertEqual((row['name'], row['type_label'], row['channel_label'], row['state'], row['state_label'], row['contacts']),
                         ('Zzq Renewals', 'Outbound', 'WhatsApp', 'draft', 'Draft', 3))

        self.assertEqual(self._ids(pill='running'), [self.helpdesk.id])
        self.assertEqual(self._ids(pill='draft'), [self.renewals.id])
        self.assertEqual(self._ids(pill='done'), [old.id])
        self.assertFalse(self._ids(pill='cancelled'))
        self.assertEqual(self._ids(pill='inbound'), [self.helpdesk.id])
        self.assertEqual(self._ids(pill='outbound'), [self.renewals.id, old.id])
        self.assertEqual(self._ids(search='zzq help'), [self.helpdesk.id])
        page = self.Ws.ws_campaigns(search='zzq', limit=2, offset=1)
        self.assertEqual(([r['id'] for r in page['rows']], page['more']), ([self.renewals.id, old.id], False))

    def test_one_campaign(self):
        anele, bongani, cebo = self.people
        self.renewals.write({'state': 'running', 'send_progress': 2, 'date_start': fields.Datetime.now()})
        self._msg(anele, self.renewals, status='delivered', minutes_ago=9)
        self._msg(bongani, self.renewals, status='failed', minutes_ago=8, failure_reason='Not on WhatsApp')
        self._msg(anele, self.renewals, status='delivered', minutes_ago=2, out=False, body_text='Thanks')
        self.env['contact.centre.automation'].create({
            'name': 'Zzq stop', 'campaign_id': self.renewals.id, 'channel': 'whatsapp',
            'trigger_type': 'keyword', 'trigger_keyword': 'STOP', 'response_type': 'text', 'response_text': 'Done.'})

        data = self.Ws.ws_campaign(self.renewals.id)
        self.assertEqual((data['name'], data['state'], data['outbound']), ('Zzq Renewals', 'running', True))
        self.assertEqual({s['label']: s['value'] for s in data['stats']},
                         {'Contacts': 3, 'Sent': 2, 'Delivered': 2, 'Failed': 1})
        self.assertEqual(data['progress'], {'done': 2, 'total': 3})
        self.assertEqual(data['template'], {'name': 'Zzq renewal reminder', 'body': 'Your cover renews on the 1st.'})
        people = {p['name']: (p['status'], p['failure']) for p in data['people']}
        self.assertEqual(people, {'Zzq Anele': ('delivered', ''), 'Zzq Bongani': ('failed', 'Not on WhatsApp'), 'Zzq Cebo': ('', '')})
        self.assertEqual(data['people_more'], 0)
        self.assertEqual([(m['name'], m['out'], m['status']) for m in data['log']],
                         [('Zzq Anele', False, 'delivered'), ('Zzq Bongani', True, 'failed'), ('Zzq Anele', True, 'delivered')])
        self.assertEqual([(a['name'], a['keyword'], a['active']) for a in data['automations']], [('Zzq stop', 'STOP', True)])
        self.assertTrue(data['started'])
        # An agent can look, not act.
        self.assertEqual((data['can_manage'], data['actions']), (False, []))
        self.assertEqual(self.Boss.ws_campaign(self.renewals.id)['actions'], ['done', 'cancel'])

        data = self.Ws.ws_campaign(self.helpdesk.id)
        self.assertEqual((data['outbound'], data['progress'], data['template'], data['rules']), (False, False, False, []))
        self.assertEqual({s['label']: s['value'] for s in data['stats']}, {'Contacts': 0, 'Messages': 0})
        with self.assertRaises(UserError):
            self.Ws.ws_campaign(0)

    def test_starting_and_stopping(self):
        with self.assertRaises(AccessError):
            self.Ws.ws_campaign_action(self.renewals.id, 'start')
        self.assertEqual(self.renewals.state, 'draft')

        self.assertEqual(self.Boss.ws_campaign(self.renewals.id)['actions'], ['start', 'cancel'])
        data = self.Boss.ws_campaign_action(self.renewals.id, 'start')
        self.assertEqual((data['state'], data['actions'], data['progress']), ('running', ['done', 'cancel'], {'done': 0, 'total': 3}))
        # Marked as running only: nothing is sent until the scheduled job picks it up.
        self.assertFalse(self.env['contact.centre.message'].search([('campaign_id', '=', self.renewals.id)]))
        # Not twice, and nothing that isn't one of the four.
        for bad in ('start', 'reset', 'unlink', ''):
            with self.assertRaises(UserError):
                self.Boss.ws_campaign_action(self.renewals.id, bad)

        self.assertEqual(self.Boss.ws_campaign_action(self.renewals.id, 'done')['state'], 'done')
        self.assertEqual(self.Boss.ws_campaign_action(self.renewals.id, 'reset')['state'], 'draft')
        self.assertEqual(self.Boss.ws_campaign_action(self.renewals.id, 'cancel')['state'], 'cancelled')

        # The campaign's own rules still decide: no template, no start.
        bare = self._campaign('Zzq Bare')
        with self.assertRaises(UserError):
            self.Boss.ws_campaign_action(bare.id, 'start')
        self.assertEqual(bare.state, 'draft')
