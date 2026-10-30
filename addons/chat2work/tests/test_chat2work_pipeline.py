# -*- coding: utf-8 -*-
"""Candidate pipeline stages: automatic moves and agent moves."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'chat2work')
class TestChat2workPipeline(TransactionCase):

    def setUp(self):
        super().setUp()
        self.cand = self.env['chat2work.candidate'].create({'name': 'Lindiwe', 'phone': '+27820003001'})

    def test_starts_new(self):
        self.assertEqual(self.cand.stage, 'new')

    def test_cv_moves_to_cv_ready(self):
        self.cand.write({'cv_state': 'uploaded'})
        self.assertEqual(self.cand.stage, 'cv_ready')

    def test_cv_help_moves_to_needs_help(self):
        self.cand._c2w_request_cv_help()
        self.assertEqual(self.cand.stage, 'help')
        self.assertEqual(self.cand.open_callback_count, 1)
        # A CV arriving afterwards takes them on to CV ready.
        self.cand.write({'cv_state': 'built'})
        self.assertEqual(self.cand.stage, 'cv_ready')

    def test_callback_request_moves_to_needs_help(self):
        self.cand.write({'cv_state': 'uploaded'})
        self.env['chat2work.callback.request'].create({'phone': self.cand.phone, 'candidate_id': self.cand.id})
        self.assertEqual(self.cand.stage, 'help')

    def test_agent_stage_is_kept(self):
        self.cand.write({'stage': 'put_forward'})
        self.cand.write({'cv_state': 'uploaded'})
        self.env['chat2work.callback.request'].create({'phone': self.cand.phone, 'candidate_id': self.cand.id})
        self.assertEqual(self.cand.stage, 'put_forward')

    def test_stage_change_is_tracked(self):
        # Changes to a record created in the same transaction aren't tracked,
        # so finish the creation's commit hooks first.
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.cand.write({'stage': 'screened'})
        self.env.flush_all()
        self.env.cr.precommit.run()  # tracking is written at commit
        tracked = self.env['mail.tracking.value'].search([
            ('mail_message_id.model', '=', 'chat2work.candidate'),
            ('mail_message_id.res_id', '=', self.cand.id),
            ('field_id.name', '=', 'stage'),
        ])
        self.assertEqual(tracked.new_value_char, 'Screened')

    def test_kanban_shows_every_stage(self):
        groups = self.env['chat2work.candidate'].read_group(
            [('id', '=', self.cand.id)], ['stage'], ['stage'])
        self.assertEqual(len(groups), 7)

    def test_erase_removes_chatter(self):
        self.cand.message_post(body='Called, no answer.')
        msgs = self.cand.message_ids
        self.cand._c2w_erase()
        self.assertFalse(msgs.exists())

    def test_cv_text_removes_id_numbers(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'cv.txt', 'raw': b'Lindiwe. ID 9308290197084. Worked in retail for three years.',
            'mimetype': 'text/plain', 'res_model': 'chat2work.candidate', 'res_id': self.cand.id,
        })
        self.cand.cv_attachment_id = attachment
        self.assertEqual(self.cand.cv_text_state, 'readable')
        self.assertNotIn('9308290197084', self.cand.cv_text)
        self.assertIn('[ID number]', self.cand.cv_text)

    def test_unreadable_cv_is_flagged(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'cv.png', 'raw': b'\x89PNG\r\n\x1a\n', 'mimetype': 'image/png',
            'res_model': 'chat2work.candidate', 'res_id': self.cand.id,
        })
        self.cand.cv_attachment_id = attachment
        self.assertEqual(self.cand.cv_text_state, 'unreadable')
        self.assertFalse(self.cand.cv_text)
