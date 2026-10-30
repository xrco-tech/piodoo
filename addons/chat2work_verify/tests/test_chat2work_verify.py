# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

MOD = 'odoo.addons.chat2work_verify.models.chat2work_verify.requests.'
ID_NO = '9111060123086'


def reply(status=200, body=None):
    response = MagicMock(status_code=status)
    response.json.return_value = body if body is not None else {}
    return response


def ok(remaining=32, status='ID Number Valid'):
    return reply(body={
        'success': True, 'requestId': 'req-1', 'remainingCredits': remaining, 'mode': 'production',
        'reportType': 'said_verification', 'input': {'idNumber': ID_NO},
        'results': {'said_verification': {'Status': 'Success', 'transaction_id': 't1', 'realTimeResults': {
            'Status': status, 'transaction_id': 't1',
            'Verification': {'Firstnames': 'NALEDI LERATO', 'Lastname': 'KHUMALO', 'Dob': '1991-11-06',
                             'Age': 34, 'Gender': 'Female', 'Citizenship': 'South African', 'DateIssued': ''},
        }}},
    })


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workVerify(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('chat2work.verifynow_api_key', 'vn_live_test')
        self.account = self.env['chat2work.verify.account']._get()
        self.account.write({'mode': 'production', 'available_credits': 33, 'balance_at': fields.Datetime.now()})
        Candidate = self.env['chat2work.candidate'].sudo()
        self.cand = Candidate.create({
            'phone': '+27820010001', 'name': False,
            'id_number_hash': Candidate._id_number_hash(ID_NO),
            'id_number_encrypted': Candidate._id_number_encrypt(ID_NO),
        })

    def _run(self, response):
        with patch(MOD + 'post', return_value=response) as post:
            check = self.cand._c2w_run_id_check()
        return check, post

    def test_production_check_fills_candidate_and_tracks_credits(self):
        check, post = self._run(ok())
        kwargs = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], 'https://www.verifynow.co.za/api/external/verify')
        self.assertEqual(kwargs['json'], {'reportType': 'said_verification', 'idNumber': ID_NO, 'mode': 'production'})
        self.assertEqual(kwargs['headers']['x-api-key'], 'vn_live_test')
        self.assertTrue(kwargs['headers']['Idempotency-Key'])
        self.assertEqual(self.cand.id_check_state, 'verified')
        self.assertEqual(self.cand.id_last_name, 'KHUMALO')
        self.assertEqual(self.cand.name, 'Naledi Lerato Khumalo')
        self.assertEqual(check.credits_used, 1)
        self.assertEqual(self.account.available_credits, 32)
        self.assertEqual(self.account.credits_used_total, 1)

    def test_candidate_given_name_is_kept(self):
        self.cand.name = 'Lerato K'
        self._run(ok())
        self.assertEqual(self.cand.name, 'Lerato K')

    def test_sandbox_never_touches_candidate_or_balance(self):
        self.account.mode = 'sandbox'
        check, post = self._run(ok(remaining=999))
        self.assertEqual(post.call_args.kwargs['json']['mode'], 'sandbox')
        self.assertEqual(check.state, 'verified')
        self.assertEqual(check.credits_used, 0)
        self.assertEqual(self.cand.id_check_state, 'none')
        self.assertFalse(self.cand.name)
        self.assertEqual(self.account.available_credits, 33)

    def test_id_number_not_kept(self):
        check, _post = self._run(ok())
        for fname, field in check._fields.items():
            if field.type in ('char', 'text'):
                self.assertNotIn(ID_NO, str(check[fname] or ''), fname)

    def test_invalid_id(self):
        check, _post = self._run(ok(status='ID Number Invalid'))
        self.assertEqual(check.state, 'not_valid')
        self.assertEqual(self.cand.id_check_state, 'not_valid')
        self.assertFalse(self.cand.id_last_name)

    def test_no_second_paid_check(self):
        self._run(ok())
        with patch(MOD + 'post') as post, self.assertRaises(UserError):
            self.cand._c2w_run_id_check()
        post.assert_not_called()

    def test_retry_after_lost_response_reuses_key(self):
        with patch(MOD + 'post', side_effect=requests.ConnectionError('boom ' + ID_NO)):
            first = self.cand._c2w_run_id_check()
        self.assertEqual(first.state, 'failed')
        self.assertNotIn(ID_NO, first.error)
        self.assertEqual(first.credits_used, 0)
        check, post = self._run(ok())
        self.assertEqual(check, first)
        self.assertEqual(post.call_args.kwargs['headers']['Idempotency-Key'], first.idempotency_key)
        self.assertEqual(self.cand.id_check_state, 'verified')

    def test_old_failure_gets_a_new_key(self):
        with patch(MOD + 'post', return_value=reply(502)):
            first = self.cand._c2w_run_id_check()
        self.env.cr.execute("UPDATE chat2work_verify_check SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(hours=72), first.id])
        first.invalidate_recordset()
        check, _post = self._run(ok())
        self.assertNotEqual(check, first)

    def test_no_credits_message(self):
        with patch(MOD + 'post', return_value=reply(402, {'error': 'x'})):
            check = self.cand._c2w_run_id_check()
        self.assertEqual(check.state, 'failed')
        self.assertIn('Not enough', check.error)

    def test_missing_key(self):
        self.env['ir.config_parameter'].sudo().set_param('chat2work.verifynow_api_key', '')
        with self.assertRaises(UserError):
            self.cand._c2w_run_id_check()

    def test_balance_refresh(self):
        with patch(MOD + 'get', return_value=reply(body={'available_credits': 100, 'source': 'organization'})) as get:
            self.account.action_refresh_balance()
        self.assertEqual(get.call_args.args[0], 'https://www.verifynow.co.za/api/external/my_credits')
        self.assertEqual(self.account.available_credits, 100)
        self.assertFalse(self.account.is_low)
        self.account.available_credits = 5
        self.account.invalidate_recordset(['is_low'])
        self.assertTrue(self.account.is_low)

    def test_auto_only_new_candidates_in_production(self):
        Candidate = self.env['chat2work.candidate'].sudo()
        self.env.cr.commit = MagicMock()
        with patch(MOD + 'post', return_value=ok()) as post:
            Candidate.env['chat2work.verify.account']._cron_auto_checks()
            post.assert_not_called()                    # off
            self.account.auto_check = True
            self.account.mode = 'sandbox'
            Candidate.env['chat2work.verify.account']._cron_auto_checks()
            post.assert_not_called()                    # sandbox
            self.account.mode = 'production'
            self.env.cr.execute("UPDATE chat2work_candidate SET create_date = %s WHERE id = %s",
                                [fields.Datetime.now() - timedelta(days=1), self.cand.id])
            self.cand.invalidate_recordset()
            Candidate.env['chat2work.verify.account']._cron_auto_checks()
            post.assert_not_called()                    # existing candidate

    def test_erase_keeps_credit_record_only(self):
        check, _post = self._run(ok())
        self.cand._c2w_erase()
        self.assertTrue(check.exists())
        self.assertFalse(check.candidate_id)
        self.assertFalse(check.last_name)
        self.assertFalse(check.dob)
        self.assertEqual(check.credits_used, 1)

    def test_only_permitted_users(self):
        agent = new_test_user(self.env, login='c2w_no_idcheck', groups='base.group_user')
        with patch(MOD + 'post') as post, self.assertRaises(UserError):
            self.cand.with_user(agent).action_c2w_id_check()
        post.assert_not_called()
