# -*- coding: utf-8 -*-
"""Retention: candidates inactive for 12 months are erased, with their CV and
callback requests; activity keeps them; admins can erase on request."""

from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

CODE = '*384*9999#'


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workRetention(TransactionCase):

    def setUp(self):
        super().setUp()
        patch('odoo.addons.chat2work.models.chat2work._send_sms', return_value=True).start()
        self.addCleanup(patch.stopall)
        self.Candidate = self.env['chat2work.candidate']
        self.Callback = self.env['chat2work.callback.request']

    def make(self, phone, months_ago):
        cand = self.Candidate.create({'name': 'C %s' % phone, 'phone': phone, 'consent_at': fields.Datetime.now()})
        cand.last_active_at = fields.Datetime.now() - relativedelta(months=months_ago)
        cand._c2w_store_cv_file('CV upload.pdf', b'%PDF-1.4', 'application/pdf', 'uploaded')
        cand.last_active_at = fields.Datetime.now() - relativedelta(months=months_ago)  # upload touched it
        self.Callback.create({'phone': phone, 'candidate_id': cand.id})
        return cand

    def test_purge_erases_only_inactive(self):
        old = self.make('+27820200001', 13)
        recent = self.make('+27820200002', 11)
        old_att = old.cv_attachment_id
        self.Candidate._cron_purge_inactive()
        self.assertFalse(old.exists())
        self.assertFalse(old_att.exists())
        self.assertFalse(self.Callback.search([('phone', '=', '+27820200001')]))
        self.assertTrue(recent.exists())
        self.assertTrue(recent.cv_attachment_id.exists())
        self.assertTrue(self.Callback.search([('phone', '=', '+27820200002')]))

    def test_archived_candidates_are_purged_too(self):
        old = self.make('+27820200003', 14)
        old.active = False
        self.Candidate._cron_purge_inactive()
        self.assertFalse(old.with_context(active_test=False).exists())

    def test_retention_months_param(self):
        cand = self.make('+27820200004', 7)
        self.env['ir.config_parameter'].sudo().set_param('chat2work.retention_months', '6')
        self.Candidate._cron_purge_inactive()
        self.assertFalse(cand.exists())

    def test_session_marks_candidate_active(self):
        cand = self.make('+27820200005', 13)
        Session = self.env['chat2work.ussd.session']
        Session.ussd_handle('ATUid_ret_1', CODE, '+27820200005', '', '')
        Session.ussd_handle('ATUid_ret_1', CODE, '+27820200005', '0', '0')   # recognised caller, Exit
        self.assertGreater(cand.last_active_at, fields.Datetime.now() - relativedelta(minutes=5))
        self.Candidate._cron_purge_inactive()
        self.assertTrue(cand.exists())

    def test_erase_on_request_admin_only(self):
        cand = self.make('+27820200006', 0)
        user = new_test_user(self.env, 'c2w_agent', groups='base.group_user')
        with self.assertRaises(AccessError):
            cand.with_user(user).action_c2w_erase()
        self.assertTrue(cand.exists())
        cand.action_c2w_erase()
        self.assertFalse(cand.exists())
        self.assertFalse(self.Callback.search([('phone', '=', '+27820200006')]))
