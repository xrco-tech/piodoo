# -*- coding: utf-8 -*-
"""Chat2Work USSD flow (spec v1.0) — walks real sessions through ussd_handle."""

from datetime import date
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.chat2work.models.chat2work_ussd import parse_sa_id

CODE = '*384*9999#'
TODAY = date.today()


def make_id(dob, seq='5009', citizen='0'):
    """Build a valid SA ID number (Luhn check digit) for a date of birth."""
    body = dob.strftime('%y%m%d') + seq + citizen + '8'
    for check in '0123456789':
        if parse_sa_id(body + check, today=TODAY):
            return body + check
    raise AssertionError('no check digit')


def years_ago(n):
    return date(TODAY.year - n, 1, 15)


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workUssd(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Session = cls.env['chat2work.ussd.session']
        cls.Candidate = cls.env['chat2work.candidate']
        cls.Callback = cls.env['chat2work.callback.request']
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('chat2work.ussd_age_min', '18')
        ICP.set_param('chat2work.ussd_age_max', '34')
        ICP.set_param('chat2work.ussd_terms_url', 'xrco.tech/c2w-terms')
        cls._sid = 0
        sms = patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True)
        sms.start()
        cls.addClassCleanup(sms.stop)

    def dial(self, phone, *inputs):
        """Run a session; return every response in order."""
        type(self)._sid += 1
        sid = 'ATUid_test_%d' % self._sid
        out, crumbs = [], []
        out.append(self.Session.ussd_handle(sid, CODE, phone, '', ''))
        for inp in inputs:
            crumbs.append(inp)
            out.append(self.Session.ussd_handle(sid, CODE, phone, '*'.join(crumbs), inp))
        return out

    # ── Create profile ───────────────────────────────────────────────────────

    def test_create_profile_whatsapp(self):
        id_no = make_id(years_ago(25))
        out = self.dial('+27820000001', '1', '1', '1', id_no, '1', '1')
        self.assertTrue(out[0].startswith('CON Welcome to Chat2Work.'))
        self.assertIn('Terms: xrco.tech/c2w-terms', out[1])
        self.assertIn('Do you use 0820000001 on WhatsApp too?', out[2])
        self.assertTrue(out[3].startswith('CON Enter your 13-digit SA ID number'))
        self.assertTrue(out[4].startswith('CON What is your current employment status?'))
        self.assertTrue(out[5].startswith('CON Are you looking for a new job?'))
        self.assertEqual(out[6], 'END Profile created! We will contact you soon via WhatsApp/SMS.')

        cand = self.Candidate.search([('phone', '=', '+27820000001')])
        self.assertEqual(len(cand), 1)
        self.assertTrue(cand.whatsapp_opt_in)
        self.assertEqual(cand.employment_status, 'unemployed')
        self.assertTrue(cand.job_seeking)
        self.assertTrue(cand.consent_at)
        self.assertTrue(cand.has_id_number)
        self.assertNotIn(id_no, cand.sudo().id_number_encrypted)
        self.assertEqual(cand.sudo()._id_number_decrypt(), id_no)
        self.assertFalse(self.Session.search([]), 'session row removed on END')

    def test_create_profile_sms_only(self):
        out = self.dial('+27820000002', '1', '1', '2', make_id(years_ago(20)), '4', '2')
        self.assertEqual(out[-1], 'END Profile created! We will contact you soon via SMS.')
        cand = self.Candidate.search([('phone', '=', '+27820000002')])
        self.assertFalse(cand.whatsapp_opt_in)
        self.assertEqual(cand.employment_status, 'student')
        self.assertFalse(cand.job_seeking)

    def test_decline_consent_stores_nothing(self):
        partners = self.env['res.partner'].search_count([])
        out = self.dial('+27820000003', '1', '2')
        self.assertEqual(out[-1], 'END No problem. Nothing was saved. Dial %s any time to start again.' % CODE)
        self.assertFalse(self.Candidate.search([('phone', '=', '+27820000003')]))
        self.assertEqual(self.env['res.partner'].search_count([]), partners)
        self.assertFalse(self.Session.search([]))

    def test_invalid_id_retry_then_lock(self):
        out = self.dial('+27820000004', '1', '1', '1', '123', '1', '9013015009087', '1', 'abc')
        self.assertTrue(out[4].startswith('CON Invalid ID number.'))
        self.assertTrue(out[5].startswith('CON Enter your 13-digit SA ID number'))
        self.assertTrue(out[6].startswith('CON Invalid ID number.'))
        self.assertEqual(out[8], 'END Too many attempts. Please try again later or dial %s '
                                 'and request a callback.' % CODE)

    def test_id_retyped_on_error_screen(self):
        id_no = make_id(years_ago(26))
        out = self.dial('+27820000014', '1', '1', '1', '1234567890123', id_no)
        self.assertTrue(out[4].startswith('CON Invalid ID number.'))
        self.assertTrue(out[5].startswith('CON What is your current employment status?'))

    def test_invalid_id_main_menu(self):
        out = self.dial('+27820000005', '1', '1', '1', '1234567890123', '0')
        self.assertTrue(out[-1].startswith('CON Welcome to Chat2Work.'))

    def test_duplicate_id(self):
        id_no = make_id(years_ago(22))
        self.dial('+27820000006', '1', '1', '1', id_no, '1', '1')
        out = self.dial('+27820000007', '1', '1', '1', id_no, '1')
        self.assertTrue(out[4].startswith('CON This ID is already registered.'))
        self.assertTrue(out[5].startswith('END Callback requested for 0820000007.'))
        self.assertTrue(self.Callback.search([('phone', '=', '+27820000007')]))

    def test_age_out_of_range(self):
        out = self.dial('+27820000008', '1', '1', '1', make_id(years_ago(45)))
        self.assertEqual(out[-1], 'END Sorry, Chat2Work is for ages 18-34. Thank you for your interest.')
        self.assertFalse(self.Candidate.search([('phone', '=', '+27820000008')]))

    def test_back_navigation(self):
        out = self.dial('+27820000009', '1', '1', '0', '1', '1', '0', '0')
        self.assertTrue(out[3].startswith('CON Chat2Work will store your details'))  # S03 → S02
        self.assertTrue(out[6].startswith('CON Do you use'))                          # S04 → S03
        self.assertTrue(out[7].startswith('CON Chat2Work will store your details'))

    # ── Recognised callers ───────────────────────────────────────────────────

    def test_recognised_update_status(self):
        cand = self.Candidate.create({'name': 'Nomvula Thandeka Mahlangu', 'phone': '+27820000010',
                                      'employment_status': 'unemployed', 'job_seeking': True})
        out = self.dial('0820000010', '1', '2', '2')
        self.assertTrue(out[0].startswith('CON Hi Nomvula Thandek. What would you like to do?'))
        self.assertEqual(out[-1], 'END Status updated. Thank you! We will be in touch soon.')
        self.assertEqual(cand.employment_status, 'employed')
        self.assertFalse(cand.job_seeking)
        self.assertTrue(cand.status_updated_at)

    def test_recognised_without_name(self):
        self.Candidate.create({'phone': '27820000011'})
        out = self.dial('+27820000011', '1', '0', '0')
        self.assertTrue(out[0].startswith('CON Welcome back to Chat2Work. What would you like to do?'))
        self.assertTrue(out[2].startswith('CON Welcome back'))                       # S08 → S01A
        self.assertEqual(out[3], 'END Session ended. Dial %s to start again.' % CODE)

    # ── Callback / system screens ────────────────────────────────────────────

    def test_callback_unrecognised(self):
        out = self.dial('+27820000012', '2')
        self.assertEqual(out[-1], 'END Callback requested for 0820000012. '
                                  'A contact centre agent will call you shortly.')
        self.assertEqual(self.Callback.search([('phone', '=', '+27820000012')]).channel, 'ussd')

    def test_invalid_choice_then_exit(self):
        out = self.dial('+27820000013', '7', '1', 'x', 'y', 'z')
        self.assertTrue(out[1].startswith('CON Invalid choice. Please try again.\nWelcome to Chat2Work.'))
        self.assertTrue(out[2].startswith('CON Chat2Work will store'), 'valid input resets the counter')
        self.assertTrue(out[4].startswith('CON Invalid choice.'))
        self.assertEqual(out[5], 'END Session ended. Dial %s to start again.' % CODE)

    def test_unknown_session_times_out(self):
        res = self.Session.ussd_handle('ATUid_gone', CODE, '+27820000014', '1*2', '2')
        self.assertEqual(res, 'END Session expired. Dial %s to start again.' % CODE)

    def test_screens_fit_160_with_invalid_prefix(self):
        cand = self.Candidate.create({'name': 'X' * 40, 'phone': '+27820000015'})
        screens = ['S01A', 'S01B', 'S02', 'S03', 'S04', 'S04-ERR1', 'S04-ERR2',
                   'S05', 'S06', 'S08', 'S09']
        session = self.Session.create({'session_id': 'len', 'msisdn': '+27820000015',
                                       'service_code': CODE, 'candidate_id': cand.id})
        for screen in screens:
            body = 'CON Invalid choice. Please try again.\n' + session._render(screen)
            self.assertLessEqual(len(body), 160, screen)

    def test_parse_sa_id(self):
        good = make_id(date(2001, 2, 28))
        self.assertEqual(parse_sa_id(good), date(2001, 2, 28))
        self.assertIsNone(parse_sa_id(good[:-1] + str((int(good[-1]) + 1) % 10)))  # checksum
        self.assertIsNone(parse_sa_id('0102305009087'))   # 30 Feb
        self.assertIsNone(parse_sa_id('12345'))
        self.assertIsNone(parse_sa_id(make_id(date(1990, 1, 1))[:10] + '2' + '80'))  # citizenship


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workUssdSimulator(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('chat2work.ussd_age_max', '34')
        cls.account = cls.env['comm.ussd.account'].create({
            'name': 'C2W Sim', 'service_code': CODE, 'flow_engine': 'chat2work'})

    def sim(self, phone, *inputs):
        wiz = self.env['chat2work.ussd.simulator'].create({'account_id': self.account.id, 'phone': phone})
        for inp in inputs:
            wiz.user_input = inp
            wiz.action_send()
        return wiz

    def test_preview_saves_nothing(self):
        counts = lambda: (self.env['chat2work.candidate'].search_count([]),
                          self.env['chat2work.callback.request'].search_count([]),
                          self.env['chat2work.ussd.session'].search_count([]),
                          self.env['res.partner'].search_count([]),
                          self.env['sms.sms'].search_count([]))
        before = counts()
        wiz = self.sim('+27830000001', '1', '1', '1', make_id(years_ago(24)), '1', '1')
        self.assertTrue(wiz.ended)
        self.assertIn('Profile created! We will contact you soon via WhatsApp/SMS.', wiz.screen_html)
        self.assertIn('Enter your 13-digit SA ID number', wiz.screen_html, 'history kept')
        wiz2 = self.sim('+27830000002', '2')
        self.assertIn('Callback requested for 0830000002.', wiz2.screen_html)
        self.assertEqual(counts(), before)

    def test_preview_recognised_and_restart(self):
        self.env['chat2work.candidate'].create({'name': 'Sipho', 'phone': '+27830000003'})
        wiz = self.sim('+27830000003', '9')
        self.assertIn('Invalid choice. Please try again.', wiz.screen_html)
        self.assertIn('Hi Sipho.', wiz.screen_html)
        self.assertFalse(wiz.ended)
        wiz.action_restart()
        self.assertFalse(wiz.inputs)
        self.assertNotIn('Invalid choice', wiz.screen_html)

    def test_open_from_menu(self):
        """The menu opens an unsaved dialog: the web client calls onchange on
        a new record, which computes screen_html before anything is saved."""
        spec = {'account_id': {}, 'service_code': {}, 'phone': {}, 'inputs': {},
                'user_input': {}, 'ended': {}, 'screen_html': {}}
        res = self.env['chat2work.ussd.simulator'].onchange({}, [], spec)
        self.assertIn('Welcome to Chat2Work.', res['value']['screen_html'])
        self.assertFalse(res['value']['inputs'])
        wiz = self.env['chat2work.ussd.simulator'].create({'phone': '+27830000009'})
        wiz.user_input = '1'
        wiz.action_send()
        self.assertIn('I agree', wiz.screen_html)

    def test_account_button(self):
        action = self.account.action_open_chat2work_simulator()
        self.assertEqual(action['res_model'], 'chat2work.ussd.simulator')
        self.assertEqual(action['target'], 'new')
