# -*- coding: utf-8 -*-
"""Each USSD or WhatsApp session leaves how long it took and how it ended."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_chat2work_ussd import CODE, make_id, years_ago


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workFlowRun(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['chat2work.ussd.session']
        cls.Run = cls.env['chat2work.flow.run']
        cls._sid = 0
        sms = patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True)
        sms.start()
        cls.addClassCleanup(sms.stop)

    def dial(self, phone, *inputs):
        type(self)._sid += 1
        sid = 'ATUid_run_%d' % self._sid
        out, crumbs = [self.Session.ussd_handle(sid, CODE, phone, '', '')], []
        for inp in inputs:
            crumbs.append(inp)
            out.append(self.Session.ussd_handle(sid, CODE, phone, '*'.join(crumbs), inp))
        return out

    def last(self):
        return self.Run.search([], order='id desc', limit=1)

    def test_sign_up(self):
        before = self.Run.search_count([])
        self.dial('+27820000701', '1', '1', '1', make_id(years_ago(25)), '1', '1', '2', '3')
        run = self.last()
        self.assertEqual(self.Run.search_count([]) - before, 1)
        self.assertEqual((run.channel, run.outcome, run.turns), ('ussd', 'signup', 8))
        self.assertEqual(run.candidate_id.phone, '+27820000701')
        self.assertGreaterEqual(run.seconds, 0)
        self.assertLess(fields.Datetime.now() - run.started_at, timedelta(minutes=1))

    def test_how_it_ended(self):
        # Declined the terms: nothing about them is kept, only that a session ended.
        self.dial('+27820000702', '1', '2')
        run = self.last()
        self.assertEqual((run.outcome, run.candidate_id.id), ('other', False))
        self.dial('+27820000702', '2')
        self.assertEqual(self.last().outcome, 'callback')
        self.env['chat2work.candidate'].create({'name': 'Zzq Bongi', 'phone': '+27820000703',
                                               'province': 'gauteng', 'field': 'retail'})
        out = self.dial('+27820000703', '1', '1', '2')
        self.assertTrue(out[-1].startswith('END Status updated.'))
        self.assertEqual((self.last().outcome, self.last().candidate_id.phone), ('update', '+27820000703'))

    def test_left_before_the_end(self):
        self.dial('+27820000704', '1', '1')
        self.Session.search([('msisdn', '=', '+27820000704')]).unlink()      # what the clean-up does
        self.assertEqual(self.last().outcome, 'abandoned')
        # The profile was saved, but they left during the questions after it.
        self.dial('+27820000705', '1', '1', '1', make_id(years_ago(25)), '1', '1')
        self.Session.ussd_session_closed('ATUid_run_%d' % self._sid)
        self.assertEqual((self.last().outcome, self.last().candidate_id.phone), ('abandoned', '+27820000705'))

    def test_how_long(self):
        """The time is from the first screen to the last one."""
        self.dial('+27820000706', '1')
        session = self.Session.search([('msisdn', '=', '+27820000706')])
        start = fields.Datetime.now() - timedelta(seconds=95)
        log = [dict(entry) for entry in session.transcript]
        log[0]['at'] = fields.Datetime.to_string(start)
        session.transcript = log
        self.Session.ussd_handle(session.session_id, CODE, '+27820000706', '1*2', '2')
        run = self.last()
        self.assertAlmostEqual(run.seconds, 95, delta=3)
        self.assertEqual(run.started_at, start.replace(microsecond=0))

    def test_simulator_is_not_counted(self):
        before = self.Run.search_count([])
        session = self.Session.with_context(chat2work_ussd_simulation=True).create(
            {'session_id': 'sim_run', 'service_code': CODE, 'msisdn': '+27820000707'})
        session._note('outbound', 'x')
        session.unlink()
        self.assertEqual(self.Run.search_count([]), before)
