# -*- coding: utf-8 -*-
"""The Calls section of the workspace: both lines in one list, the filters,
one call, and its outcome. Nothing here places a call or transcribes one."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'contact_centre')
class TestContactCentreWorkspaceCalls(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(cls.env, 'ccw_calls_agent',
                                  groups='base.group_user,contact_centre.group_contact_centre_agent')
        cls.outsider = new_test_user(cls.env, 'ccw_calls_outsider', groups='base.group_user')
        cls.Ws = cls.env['contact.centre.workspace'].with_user(cls.agent)
        cls.lerato = cls.env['res.partner'].create({'name': 'Lerato Dube', 'mobile': '27990000311'})
        cls.count = 0

    def _wa(self, minutes_ago, incoming=True, status='answered', duration=0, partner=None, number='27990000311', **vals):
        type(self).count += 1
        at = fields.Datetime.now() - timedelta(minutes=minutes_ago)
        return self.env['whatsapp.call.log'].create(dict({
            'call_id': 'ccw_call_%s' % self.count,
            'call_direction': 'incoming' if incoming else 'outgoing',
            'call_status': status, 'call_timestamp': at, 'duration': duration,
            'from_number': number if incoming else '27100000000',
            'to_number': '27100000000' if incoming else number,
            'partner_id': partner.id if partner else False,
            'agent_user_id': self.agent.id,
        }, **vals))

    def _voip(self, minutes_ago, incoming=False, state='completed', duration=0, partner=None, number='27990000311', **vals):
        at = fields.Datetime.now() - timedelta(minutes=minutes_ago)
        return self.env['comm.voip.call'].create(dict({
            'direction': 'incoming' if incoming else 'outgoing', 'state': state,
            'start_time': at, 'duration': duration,
            'from_number': number if incoming else '27100000000',
            'to_number': '27100000000' if incoming else number,
            'partner_id': partner.id if partner else False,
            'agent_user_id': self.agent.id,
        }, **vals))

    def _keys(self, **kwargs):
        """The listed calls for our test numbers, leaving out any the database already had."""
        kwargs.setdefault('search', '2799000031')
        return [row['key'] for row in self.Ws.ws_calls(**kwargs)['rows']]

    def test_agents_only(self):
        call = self._wa(5, partner=self.lerato)
        key = 'wa-%s' % call.id
        Outsider = self.env['contact.centre.workspace'].with_user(self.outsider)
        for attempt in (Outsider.ws_calls, lambda: Outsider.ws_call(key),
                        lambda: Outsider.ws_call_outcome(key, False, 'x'),
                        lambda: Outsider.ws_call_transcribe(key)):
            with self.assertRaises(AccessError):
                attempt()

    def test_list_both_lines_newest_first(self):
        answered = self._wa(40, duration=192, partner=self.lerato)
        missed = self._wa(30, status='ended', partner=self.lerato)
        voip = self._voip(20, duration=65, partner=self.lerato)
        no_answer = self._voip(10, state='no_answer', number='27990000312')
        missed_voip = self._voip(5, incoming=True, state='no_answer', number='27990000313')
        declined = self._wa(2, incoming=False, status='declined', number='27990000314')
        wa = lambda call: 'wa-%s' % call.id
        vo = lambda call: 'voip-%s' % call.id

        self.assertEqual(self._keys(), [wa(declined), vo(missed_voip), vo(no_answer), vo(voip), wa(missed), wa(answered)])
        rows = {row['key']: row for row in self.Ws.ws_calls(search='2799000031')['rows']}
        row = rows[wa(answered)]
        self.assertEqual((row['line'], row['name'], row['number'], row['incoming'], row['kind'], row['duration'], row['initials']),
                         ('whatsapp', 'Lerato Dube', '27990000311', True, 'answered', '3:12', 'LD'))
        self.assertEqual(rows[wa(missed)]['kind'], 'missed')
        self.assertEqual((rows[vo(voip)]['line'], rows[vo(voip)]['kind'], rows[vo(voip)]['duration']), ('voip', 'answered', '1:05'))
        # An outgoing call nobody picked up is not a missed call; an incoming one is.
        self.assertEqual((rows[vo(no_answer)]['kind'], rows[vo(no_answer)]['name']), ('unanswered', '27990000312'))
        self.assertEqual(rows[vo(missed_voip)]['kind'], 'missed')
        self.assertEqual((rows[wa(declined)]['kind'], rows[wa(declined)]['initials']), ('unanswered', '#'))

        self.assertEqual(self._keys(pill='missed'), [vo(missed_voip), wa(missed)])
        self.assertEqual(self._keys(pill='incoming'), [vo(missed_voip), wa(missed), wa(answered)])
        self.assertEqual(self._keys(pill='outgoing'), [wa(declined), vo(no_answer), vo(voip)])
        self.assertEqual(self._keys(pill='whatsapp'), [wa(declined), wa(missed), wa(answered)])
        self.assertEqual(self._keys(pill='voip'), [vo(missed_voip), vo(no_answer), vo(voip)])
        # Only calls that connected are waiting for an outcome.
        self.assertEqual(self._keys(pill='no_outcome'), [wa(answered)])
        self.assertEqual(self._keys(search='lerato'), [vo(voip), wa(missed), wa(answered)])
        self.assertEqual(self._keys(search='099 000 0312'), [vo(no_answer)])

        page = self.Ws.ws_calls(search='2799000031', limit=2)
        self.assertEqual(([r['key'] for r in page['rows']], page['more']), ([wa(declined), vo(missed_voip)], True))
        page = self.Ws.ws_calls(search='2799000031', limit=2, offset=4)
        self.assertEqual(([r['key'] for r in page['rows']], page['more']), ([wa(missed), wa(answered)], False))

    def test_one_call(self):
        earlier = self._voip(300, duration=30, partner=self.lerato)
        call = self._wa(40, duration=192, partner=self.lerato)
        self._wa(10, number='27990000399')       # someone else
        key = 'wa-%s' % call.id

        data = self.Ws.ws_call(key)
        self.assertEqual((data['key'], data['name'], data['kind'], data['has_outcome']), (key, 'Lerato Dube', 'answered', True))
        self.assertEqual([row['key'] for row in data['history']], ['voip-%s' % earlier.id])
        self.assertEqual(data['recordings'], [])
        self.assertFalse(data['can_transcribe'])
        labels = {d['label']: d['value'] for d in data['details']}
        self.assertEqual((labels['Line'], labels['Agent'], labels['From']), ('WhatsApp', self.agent.name, '27990000311'))
        # The call was copied into Lerato's conversation: that is where "Open the conversation" goes.
        contact = self.env['contact.centre.contact'].search([('partner_id', '=', self.lerato.id)])
        self.assertEqual(data['contact_id'], contact.id)

        data = self.Ws.ws_call('voip-%s' % earlier.id)
        self.assertEqual((data['line'], data['has_outcome'], data['contact_id']), ('voip', False, contact.id))
        self.assertEqual([row['key'] for row in data['history']], [key])

        for bad in ('wa-0', 'fax-3', '', 'wa-x'):
            with self.assertRaises(UserError):
                self.Ws.ws_call(bad)

    def test_recording(self):
        call = self._wa(40, duration=60, partner=self.lerato)
        attachment = self.env['ir.attachment'].create({
            'name': 'call.webm', 'res_model': 'whatsapp.call.log', 'res_id': call.id,
            'res_field': 'recording_ids', 'raw': b'audio', 'mimetype': 'audio/webm'})
        data = self.Ws.ws_call('wa-%s' % call.id)
        self.assertEqual([r['url'] for r in data['recordings']], ['/whatsapp/call/recording/%s' % attachment.id])
        self.assertTrue(self.Ws.ws_calls(search='27990000311')['rows'][0]['recorded'])

    def test_outcome(self):
        outcome = self.env['comm.disposition'].search([], limit=1) or self.env['comm.disposition'].create({'name': 'Resolved'})
        call = self._wa(40, duration=60, partner=self.lerato)
        key = 'wa-%s' % call.id
        self.Ws.ws_call_outcome(key, outcome.id, 'Sent the form')
        self.assertEqual((call.disposition_id, call.disposition_note), (outcome, 'Sent the form'))
        data = self.Ws.ws_call(key)
        self.assertEqual((data['disposition_id'], data['note'], data['disposition']), (outcome.id, 'Sent the form', outcome.name))
        self.assertFalse(self._keys(pill='no_outcome'))
        self.Ws.ws_call_outcome(key, False, '')
        self.assertFalse(call.disposition_id)

        # A VoIP call keeps a note only.
        voip = self._voip(20, duration=65, partner=self.lerato)
        self.Ws.ws_call_outcome('voip-%s' % voip.id, outcome.id, 'Will call back')
        self.assertEqual(voip.notes, 'Will call back')
        self.assertEqual(self.Ws.ws_call('voip-%s' % voip.id)['note'], 'Will call back')
