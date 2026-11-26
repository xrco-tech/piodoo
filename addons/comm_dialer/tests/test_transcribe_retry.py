# -*- coding: utf-8 -*-
"""A call whose transcription is cut short must not be started again by every run."""
import base64
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


class Killed(BaseException):
    """Stands in for the job being killed: not an Exception, so nothing in the way catches it."""


@tagged('post_install', '-at_install')
class TestTranscribeRetry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Call = cls.env['comm.voip.call']
        cls.Call.search([]).write({'transcript_state': 'done'})
        cls.calls = cls.Call.create([{}, {}])
        for call in cls.calls:
            cls.env['ir.attachment'].create({
                'name': 'rec.webm', 'mimetype': 'audio/webm', 'datas': base64.b64encode(b'audio'),
                'res_model': 'comm.voip.call', 'res_id': call.id, 'res_field': 'recording_ids'})
        cls.calls.invalidate_recordset()

    def test_killed_run_is_not_started_again(self):
        model = type(self.Call)
        # Not assertRaises: that rolls back what was written before the run died.
        died = False
        with patch.object(model, '_transcribe_recording', side_effect=Killed()):
            try:
                self.Call._cron_transcribe_pending()
            except Killed:
                died = True
        self.assertTrue(died)
        first = self.calls.filtered(lambda call: call.transcript_state == 'failed')
        second = self.calls - first
        self.assertEqual(len(first), 1, "marked before it started, so the next run skips it")
        self.assertEqual(second.transcript_state, 'none')
        with patch.object(model, '_transcribe_recording', return_value='Hello there'), \
                patch.object(model, '_run_ai_insights', return_value={}):
            self.Call._cron_transcribe_pending()
        self.assertEqual(first.transcript_state, 'failed', "left for a person to retry")
        self.assertEqual((second.transcript_state, second.transcript), ('done', 'Hello there'))
        with patch.object(model, '_transcribe_recording', return_value='Hello again'), \
                patch.object(model, '_run_ai_insights', return_value={}):
            first.action_transcribe()
        self.assertEqual((first.transcript_state, first.transcript), ('done', 'Hello again'))
