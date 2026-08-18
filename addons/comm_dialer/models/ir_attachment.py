# -*- coding: utf-8 -*-
from odoo import models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _is_call_recording(self):
        # Include VoIP/dialer call recordings in the same delete-gating that
        # comm_whatsapp_calling applies to WhatsApp recordings.
        recs = super()._is_call_recording()
        return recs | self.filtered(
            lambda a: a.res_model == 'comm.voip.call' and a.res_field == 'recording_ids')
