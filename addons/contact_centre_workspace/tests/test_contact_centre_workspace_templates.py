# -*- coding: utf-8 -*-
"""The Templates section of the workspace: the list and its filters, one
template and where it is used, and who may write, correct or archive one.
Nothing here sends a template."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceTemplates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_tpl_agent', groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.manager = new_test_user(cls.env, 'ccw_tpl_manager', groups='base.group_user,contact_centre.group_contact_centre_manager')
        cls.outsider = new_test_user(cls.env, 'ccw_tpl_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.Boss = cls.env['contact.centre.workspace'].with_user(cls.manager)
        Template = cls.env['contact.centre.template']
        cls.renewal = Template.create({'name': 'Zzq Renewal reminder', 'channel': 'whatsapp',
                                       'body_text': 'Your cover renews\non the 1st.', 'notes': 'Send a week before.'})
        cls.welcome = Template.create({'name': 'Zzq Welcome', 'channel': 'sms', 'body_text': 'Welcome to XR Co.'})
        cls.receipt = Template.create({'name': 'Zzq Receipt', 'channel': 'email', 'body_text': 'Thank you for your payment.'})
        cls.old = Template.create({'name': 'Zzq Old offer', 'channel': 'sms', 'body_text': 'Winter special.', 'active': False})

    def _ids(self, **kwargs):
        kwargs.setdefault('search', 'zzq')
        return [row['id'] for row in self.Ws.ws_templates(**kwargs)['rows']]

    def test_agents_only(self):
        Outsider = self.env['contact.centre.workspace'].with_user(self.outsider)
        for attempt in (Outsider.ws_templates, lambda: Outsider.ws_template(self.renewal.id),
                        lambda: Outsider.ws_template_save(self.renewal.id, {'name': 'X'}),
                        lambda: Outsider.ws_template_archive(self.renewal.id)):
            with self.assertRaises(AccessError):
                attempt()

    def test_list(self):
        self.assertEqual(self._ids(), [self.receipt.id, self.renewal.id, self.welcome.id])     # by name, archived left out
        result = self.Ws.ws_templates(search='zzq')
        self.assertEqual((result['total'], result['more'], result['can_manage']), (3, False, False))
        self.assertTrue(self.Boss.ws_templates(search='zzq')['can_manage'])
        row = {r['id']: r for r in result['rows']}[self.renewal.id]
        self.assertEqual((row['name'], row['channel'], row['channel_label'], row['preview'], row['active']),
                         ('Zzq Renewal reminder', 'whatsapp', 'WhatsApp', 'Your cover renews on the 1st.', True))

        self.assertEqual(self._ids(pill='whatsapp'), [self.renewal.id])
        self.assertEqual(self._ids(pill='sms'), [self.welcome.id])
        self.assertEqual(self._ids(pill='email'), [self.receipt.id])
        self.assertEqual(self._ids(pill='archived'), [self.old.id])
        # The wording is searched too.
        self.assertEqual(self._ids(search='thank you for your payment'), [self.receipt.id])
        page = self.Ws.ws_templates(search='zzq', limit=2)
        self.assertEqual(([r['id'] for r in page['rows']], page['more']), ([self.receipt.id, self.renewal.id], True))
        self.assertEqual(self._ids(limit=2, offset=2), [self.welcome.id])

    def test_one_template(self):
        partner = self.env['res.partner'].create({'name': 'Zzq Anele', 'mobile': '27990000611'})
        contact = self.env['contact.centre.contact'].create({'partner_id': partner.id})
        campaign = self.env['contact.centre.campaign'].create({
            'name': 'Zzq Renewals', 'campaign_type': 'outbound', 'channel': 'whatsapp', 'template_id': self.renewal.id,
            'state': 'running'})
        self.env['contact.centre.automation'].create({
            'name': 'Zzq remind', 'campaign_id': campaign.id, 'channel': 'whatsapp', 'trigger_type': 'keyword',
            'trigger_keyword': 'WHEN', 'response_type': 'template', 'template_id': self.renewal.id})
        for minutes in (50, 20):
            self.env['contact.centre.message'].create({
                'contact_id': contact.id, 'channel': 'whatsapp', 'direction': 'outbound', 'body_text': 'x', 'status': 'sent',
                'template_id': self.renewal.id, 'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes)})

        data = self.Ws.ws_template(self.renewal.id)
        self.assertEqual((data['name'], data['channel'], data['body'], data['notes'], data['active']),
                         ('Zzq Renewal reminder', 'whatsapp', 'Your cover renews\non the 1st.', 'Send a week before.', True))
        self.assertEqual(data['sent'], 2)
        self.assertTrue(data['last_sent'])
        self.assertEqual([(c['name'], c['state'], c['running']) for c in data['campaigns']], [('Zzq Renewals', 'Running', True)])
        self.assertEqual([(a['name'], a['campaign']) for a in data['automations']], [('Zzq remind', 'Zzq Renewals')])
        self.assertFalse(data['native'])
        self.assertFalse(data['can_manage'])

        data = self.Ws.ws_template(self.old.id)          # an archived one can still be opened
        self.assertEqual((data['active'], data['sent'], data['last_sent'], data['campaigns']), (False, 0, False, []))
        with self.assertRaises(UserError):
            self.Ws.ws_template(0)

    def test_writing_and_correcting(self):
        with self.assertRaises(AccessError):
            self.Ws.ws_template_save(False, {'name': 'Zzq X', 'channel': 'sms', 'body_text': 'x'})
        with self.assertRaises(AccessError):
            self.Ws.ws_template_save(self.welcome.id, {'body_text': 'changed'})
        self.assertEqual(self.welcome.body_text, 'Welcome to XR Co.')

        data = self.Boss.ws_template_save(False, {'name': '  Zzq  Thanks ', 'channel': 'sms', 'body_text': ' Thank you. \n', 'notes': ''})
        created = self.env['contact.centre.template'].browse(data['id'])
        self.assertEqual((created.name, created.channel, created.body_text, created.notes, created.active),
                         ('Zzq Thanks', 'sms', 'Thank you.', False, True))
        for bad in ({'channel': 'sms', 'body_text': 'x'}, {'name': 'Zzq', 'channel': 'sms'}, {'name': 'Zzq', 'body_text': 'x'},
                    {'name': 'Zzq', 'channel': 'fax', 'body_text': 'x'}, {'name': ' ', 'channel': 'sms', 'body_text': 'x'}):
            with self.assertRaises(UserError):
                self.Boss.ws_template_save(False, bad)

        data = self.Boss.ws_template_save(self.welcome.id, {'body_text': 'Welcome to XR Co. Save this number.', 'notes': 'New wording'})
        self.assertEqual((data['body'], data['notes'], data['name']), ('Welcome to XR Co. Save this number.', 'New wording', 'Zzq Welcome'))
        with self.assertRaises(UserError):
            self.Boss.ws_template_save(self.welcome.id, {'body_text': '  '})
        # Anything else that is sent is ignored.
        self.Boss.ws_template_save(self.welcome.id, {'active': False, 'wa_template_id': 5})
        self.assertTrue(self.welcome.active)

        # A template a campaign uses keeps its channel; one nothing uses can move.
        self.env['contact.centre.campaign'].create({
            'name': 'Zzq Renewals', 'campaign_type': 'outbound', 'channel': 'whatsapp', 'template_id': self.renewal.id})
        with self.assertRaises(UserError):
            self.Boss.ws_template_save(self.renewal.id, {'channel': 'sms'})
        self.assertEqual(self.Boss.ws_template_save(self.receipt.id, {'channel': 'sms'})['channel'], 'sms')

    def test_archiving(self):
        with self.assertRaises(AccessError):
            self.Ws.ws_template_archive(self.welcome.id)
        self.assertFalse(self.Boss.ws_template_archive(self.welcome.id)['active'])
        self.assertEqual(self._ids(pill='sms'), [])
        self.assertEqual(self._ids(pill='archived'), [self.old.id, self.welcome.id])
        self.assertTrue(self.Boss.ws_template_archive(self.welcome.id, False)['active'])
        self.assertEqual(self._ids(pill='sms'), [self.welcome.id])
