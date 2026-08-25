# -*- coding: utf-8 -*-
from odoo import models


class WhatsappCallLog(models.Model):
    # Give WhatsApp calls the same Whisper transcription + Claude insights as VoIP.
    _name = 'whatsapp.call.log'
    _inherit = ['whatsapp.call.log', 'comm.call.transcription.mixin']

    def _transcript_speaker_labels(self):
        # Label the remote side with the partner's name when known.
        partner = self.partner_id if 'partner_id' in self._fields else False
        caller = (partner.name if partner else '') or 'Caller'
        return 'Agent', caller
