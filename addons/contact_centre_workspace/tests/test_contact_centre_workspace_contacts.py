# -*- coding: utf-8 -*-
"""The Contacts section of the workspace: the directory and its filters, one
contact, correcting their details, tags, and adding a contact."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceContacts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_contacts_agent',
                                  groups='base.group_user,base.group_partner_manager,contact_centre.group_contact_centre_agent')
        cls.outsider = new_test_user(cls.env, 'ccw_contacts_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.zanele = cls._contact('Zzq Zanele Mokoena', '27990000411', 'zanele@example.com')
        cls.sipho = cls._contact('Zzq Sipho Ndlovu', '27990000422', False)
        cls.busi = cls._contact('Zzq Busi Zulu', False, 'busi@example.com')
        cls.vip = cls.env['contact.centre.tag'].create({'name': 'Zzq VIP'})

    @classmethod
    def _contact(cls, name, mobile, email):
        partner = cls.env['res.partner'].create({'name': name, 'mobile': mobile, 'email': email})
        return cls.env['contact.centre.contact'].create({'partner_id': partner.id})

    def _msg(self, contact, body, channel='whatsapp', out=False, minutes_ago=0, **vals):
        return self.env['contact.centre.message'].create(dict({
            'contact_id': contact.id, 'channel': channel, 'direction': 'outbound' if out else 'inbound',
            'body_text': body, 'status': 'sent' if out else 'delivered',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _ids(self, **kwargs):
        """The listed contacts of this test, leaving out any the database already had."""
        kwargs.setdefault('search', 'zzq')
        return [row['id'] for row in self.Ws.ws_contacts(**kwargs)['rows']]

    def test_agents_only(self):
        Outsider = self.env['contact.centre.workspace'].with_user(self.outsider)
        for attempt in (Outsider.ws_contacts, Outsider.ws_contact_tags,
                        lambda: Outsider.ws_contact(self.sipho.id),
                        lambda: Outsider.ws_contact_save(self.sipho.id, {'name': 'X'}),
                        lambda: Outsider.ws_contact_set_tags(self.sipho.id, []),
                        lambda: Outsider.ws_contact_create({'name': 'X'})):
            with self.assertRaises(AccessError):
                attempt()

    def test_directory(self):
        self._msg(self.sipho, 'Hello', minutes_ago=60)
        self._msg(self.zanele, 'Hi', minutes_ago=60 * 24 * 45)
        self.zanele.tag_ids = self.vip

        # By name; the "last 30 days" filter lists the latest first instead.
        self.assertEqual(self._ids(), [self.busi.id, self.sipho.id, self.zanele.id])
        result = self.Ws.ws_contacts(search='zzq')
        self.assertEqual((result['total'], result['more']), (3, False))
        row = {r['id']: r for r in result['rows']}[self.zanele.id]
        self.assertEqual((row['name'], row['phone'], row['email'], row['initials'], row['tags']),
                         ('Zzq Zanele Mokoena', '27990000411', 'zanele@example.com', 'ZM', ['Zzq VIP']))
        self.assertTrue(row['at'])

        self.assertEqual(self._ids(pill='recent'), [self.sipho.id])
        self.assertEqual(self._ids(pill='never'), [self.busi.id])
        self.assertEqual(self._ids(tag_id=self.vip.id), [self.zanele.id])
        self.assertFalse(self._ids(pill='campaign'))
        campaign = self.env['contact.centre.campaign'].create({
            'name': 'Zzq Renewals', 'campaign_type': 'outbound', 'channel': 'both'})
        campaign.write({'state': 'running', 'contact_ids': [(4, self.busi.id)]})
        self.assertEqual(self._ids(pill='campaign'), [self.busi.id])

        # A number is found however it is typed; an email by any part of it.
        self.assertEqual(self._ids(search='099 000 0422'), [self.sipho.id])
        self.assertEqual(self._ids(search='busi@'), [self.busi.id])
        page = self.Ws.ws_contacts(search='zzq', limit=2)
        self.assertEqual(([r['id'] for r in page['rows']], page['more']), ([self.busi.id, self.sipho.id], True))
        self.assertEqual(self._ids(limit=2, offset=2), [self.zanele.id])
        self.assertIn('Zzq VIP', [tag['name'] for tag in self.Ws.ws_contact_tags()])

    def test_one_contact(self):
        self._msg(self.sipho, 'Hello', minutes_ago=50)
        self._msg(self.sipho, 'Hi Sipho', out=True, minutes_ago=45)
        self._msg(self.sipho, 'Outgoing call, 2:10', channel='voice', out=True, minutes_ago=40)
        self._msg(self.sipho, 'Are you there?', channel='sms', minutes_ago=5)
        campaign = self.env['contact.centre.campaign'].create({
            'name': 'Zzq Renewals', 'campaign_type': 'outbound', 'channel': 'both'})
        campaign.write({'contact_ids': [(4, self.sipho.id)]})

        data = self.Ws.ws_contact(self.sipho.id)
        self.assertEqual((data['name'], data['phone'], data['email'], data['state'], data['initials']),
                         ('Zzq Sipho Ndlovu', '27990000422', '', 'open', 'ZN'))
        self.assertEqual({s['label']: s['value'] for s in data['stats']},
                         {'Messages': 3, 'Calls': 1, 'From them': 2, 'From us': 2})
        self.assertEqual(data['channels'], ['SMS', 'Voice', 'WhatsApp'])
        self.assertEqual([m['preview'] for m in data['recent']],
                         ['Are you there?', 'Outgoing call, 2:10', 'Hi Sipho', 'Hello'])
        self.assertEqual((data['recent'][0]['channel'], data['recent'][0]['out']), ('sms', False))
        self.assertEqual(data['waiting'], 1)          # the SMS has had no answer
        self.assertTrue(data['first'] < data['last'])
        self.assertEqual([(c['name'], c['channel'], c['state'], c['running']) for c in data['campaigns']],
                         [('Zzq Renewals', 'WhatsApp & SMS', 'Draft', False)])
        # Looking at a contact here is not reading their conversation.
        self.assertFalse(self.sipho.ws_seen_at)

        data = self.Ws.ws_contact(self.busi.id)
        self.assertEqual((data['recent'], data['first'], data['last'], data['waiting']), ([], False, False, 0))
        with self.assertRaises(UserError):
            self.Ws.ws_contact(0)

    def test_correcting_details(self):
        data = self.Ws.ws_contact_save(self.sipho.id, {'name': '  Zzq Sipho   Ndlovu-Khumalo ', 'email': 'sipho@example.com'})
        self.assertEqual((data['name'], data['email'], data['phone']),
                         ('Zzq Sipho Ndlovu-Khumalo', 'sipho@example.com', '27990000422'))
        # They are the person's own details, so their record changes too.
        self.assertEqual(self.sipho.partner_id.name, 'Zzq Sipho Ndlovu-Khumalo')
        self.assertEqual(self.sipho.partner_id.email, 'sipho@example.com')
        self.Ws.ws_contact_save(self.sipho.id, {'phone_number': ''})
        self.assertFalse(self.sipho.phone_number)

        for bad in ({'name': ' '}, {'email': 'not an email'}, {'phone_number': '12'}):
            with self.assertRaises(UserError):
                self.Ws.ws_contact_save(self.sipho.id, bad)
        # Anything else that is sent is ignored.
        self.Ws.ws_contact_save(self.sipho.id, {'state': 'resolved', 'partner_id': self.busi.partner_id.id})
        self.assertEqual((self.sipho.state or 'open', self.sipho.partner_id.name), ('open', 'Zzq Sipho Ndlovu-Khumalo'))

    def test_tagging(self):
        other = self.env['contact.centre.tag'].create({'name': 'Zzq Follow up'})
        self.assertEqual(sorted(self.Ws.ws_contact_set_tags(self.busi.id, [self.vip.id, other.id, 0])), sorted((self.vip | other).ids))
        self.assertEqual(self.Ws.ws_contact(self.busi.id)['tag_ids'], self.busi.tag_ids.ids)
        self.assertEqual(self.Ws.ws_contact_set_tags(self.busi.id, []), [])

    def test_adding(self):
        result = self.Ws.ws_contact_create({'name': 'Zzq Lindiwe Dlamini', 'phone_number': '2799 000 0433', 'email': ''})
        self.assertFalse(result['existing'])
        contact = self.env['contact.centre.contact'].browse(result['id'])
        self.assertEqual((contact.name, contact.phone_number, contact.partner_id.mobile),
                         ('Zzq Lindiwe Dlamini', '27990000433', '27990000433'))

        # The same number again, typed the local way, is the same person.
        again = self.Ws.ws_contact_create({'name': 'Someone else', 'phone_number': '099 000 0411'})
        self.assertEqual(again, {'id': self.zanele.id, 'existing': True})

        # A number alone is enough; nothing at all is not.
        result = self.Ws.ws_contact_create({'phone_number': '27990000444'})
        self.assertEqual(self.env['contact.centre.contact'].browse(result['id']).name, '27990000444')
        for bad in ({}, {'name': ' ', 'phone_number': ''}, {'name': 'X', 'email': 'nope'}):
            with self.assertRaises(UserError):
                self.Ws.ws_contact_create(bad)
