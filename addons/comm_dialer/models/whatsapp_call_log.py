# -*- coding: utf-8 -*-
from odoo import models


class WhatsappCallLog(models.Model):
    # Give WhatsApp calls the same Whisper transcription + Claude insights as VoIP.
    _name = 'whatsapp.call.log'
    _inherit = ['whatsapp.call.log', 'comm.call.transcription.mixin']
