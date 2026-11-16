# -*- coding: utf-8 -*-
"""What a campaign and a call cost, and who gets to see it. Skipped when the
billing app is not installed: the workspace does not depend on it."""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceCosts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.billing = 'comm.billing.event' in cls.env
        if not cls.billing:
            return
        cls.agent = new_test_user(cls.env, 'ccw_cost_agent', groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.boss = new_test_user(
            cls.env, 'ccw_cost_boss',
            groups='base.group_user,contact_centre.group_contact_centre_agent,comm_billing_core.group_billing_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.Boss = cls.env['contact.centre.workspace'].with_user(cls.boss)
        cls.currency = cls.env.company.currency_id
        cls.people = cls.env['contact.centre.contact']
        for name, mobile in (('Zzc Anele', '27990000611'), ('Zzc Bongani', '27990000622'), ('Zzc Cebo', '27990000633')):
            partner = cls.env['res.partner'].create({'name': name, 'mobile': mobile})
            cls.people |= cls.env['contact.centre.contact'].create({'partner_id': partner.id})
        cls.campaign = cls.env['contact.centre.campaign'].create({
            'name': 'Zzc Specials', 'campaign_type': 'outbound', 'channel': 'both',
            'contact_ids': [(6, 0, cls.people.ids)]})
        cls.seq = 0

    def setUp(self):
        super().setUp()
        if not self.billing:
            self.skipTest('comm_billing_core is not installed')

    def _charge(self, source_model, source_id, cost, **vals):
        event = self.env['comm.billing.event'].create(dict({
            'channel': 'whatsapp', 'category': 'marketing', 'provider': 'Meta',
            'source_model': source_model, 'source_id': source_id}, **vals))
        event.write({'price_local': cost, 'price_usd': cost / 16.0, 'fx_rate': 16.0,
                     'currency_id': self.currency.id})
        return event

    def _sent(self, contact, minutes_ago=60, **vals):
        return self.env['contact.centre.message'].create(dict({
            'contact_id': contact.id, 'campaign_id': self.campaign.id, 'channel': 'whatsapp',
            'direction': 'outbound', 'body_text': 'Specials this week', 'status': 'delivered',
            'message_timestamp': fields.Datetime.now() - timedelta(minutes=minutes_ago)}, **vals))

    def _wa_message(self, wamid):
        return self.env['whatsapp.message'].create({
            'message_id': wamid, 'wa_id': '27990000611', 'message_timestamp': fields.Datetime.now()})

    def test_campaign_cost_and_replies(self):
        anele, bongani, cebo = self.people
        first, second = self._wa_message('wamid.ZZC1'), self._wa_message('wamid.ZZC2')
        self._sent(anele, provider_message_id='wamid.ZZC1')
        self._sent(bongani, provider_message_id='wamid.ZZC2')
        sms = self.env['sms.sms'].create({'number': '27990000633', 'body': 'Specials this week'})
        self._sent(cebo, channel='sms', sms_id=sms.id)
        self._charge('whatsapp.message', first.id, 0.80)
        self._charge('whatsapp.message', second.id, 0.80)
        self._charge('sms.sms', sms.id, 0.40, channel='sms', category='sms_outbound_domestic')
        # A charge for somebody else's message is not this campaign's.
        self._charge('whatsapp.message', self._wa_message('wamid.OTHER').id, 9.0)
        # Anele wrote back; Bongani's old message from before the campaign is not a reply.
        self.env['contact.centre.message'].create({
            'contact_id': anele.id, 'channel': 'whatsapp', 'direction': 'inbound', 'body_text': 'Yes please',
            'status': 'delivered', 'message_timestamp': fields.Datetime.now() - timedelta(minutes=5)})
        self.env['contact.centre.message'].create({
            'contact_id': bongani.id, 'channel': 'whatsapp', 'direction': 'inbound', 'body_text': 'Hello',
            'status': 'delivered', 'message_timestamp': fields.Datetime.now() - timedelta(days=3)})

        cost = self.Boss.ws_campaign(self.campaign.id)['cost']
        stats = {stat['label']: stat['value'] for stat in cost['stats']}
        self.assertEqual(stats['Replied'], 1)
        self.assertEqual(stats['Charges'], 3)
        self.assertEqual(stats['Cost'], self.currency.format(2.0))
        self.assertEqual(stats['Per reply'], self.currency.format(2.0))

    def test_no_charges_yet(self):
        self._sent(self.people[0])
        cost = self.Boss.ws_campaign(self.campaign.id)['cost']
        stats = {stat['label']: stat['value'] for stat in cost['stats']}
        self.assertEqual((stats['Charges'], stats['Replied'], stats['Per reply']), (0, 0, '—'))
        self.assertIn('Nothing has been charged', cost['note'])

    def test_only_billing_people_see_costs(self):
        self.assertFalse(self.Ws.ws_campaign(self.campaign.id)['cost'])
        call = self.env['whatsapp.call.log'].create({
            'call_id': 'zzc-call-1', 'from_number': '27990000611', 'to_number': '27108221225',
            'call_direction': 'incoming', 'call_status': 'answered', 'duration': 120,
            'call_timestamp': fields.Datetime.now() - timedelta(minutes=10)})
        # The billing adapter may already have charged the call; replace it with a known amount.
        self.env['comm.billing.event'].search([
            ('source_model', '=', 'whatsapp.call.log'), ('source_id', '=', call.id)]).unlink()
        key = 'wa-%s' % call.id
        labels = lambda ws: {d['label']: d['value'] for d in ws.ws_call(key)['details']}  # noqa: E731
        self.assertEqual(labels(self.Boss)['Cost'], '', 'no charge, nothing to show')
        event = self._charge('whatsapp.call.log', call.id, 1.42, category='call_minute', unit='minute', unit_qty=2.0)
        self.assertEqual(labels(self.Ws)['Cost'], '')
        self.assertEqual(labels(self.Boss)['Cost'], 'No rate yet')
        rate_card = self.env['comm.billing.rate.card'].search([], limit=1)
        if rate_card:
            rate = self.env['comm.billing.rate'].create({
                'card_id': rate_card.id, 'category': 'call_minute', 'unit': 'minute', 'price_usd': 0.04})
            event.write({'rate_id': rate.id})
            self.assertEqual(labels(self.Boss)['Cost'], self.currency.format(1.42))
