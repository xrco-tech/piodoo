# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreSMSConfig(models.Model):
    """SMS configuration - TODO: Implement"""
    _name = 'contact.centre.sms.config'
    _description = 'SMS Configuration'

    name = fields.Char('Configuration Name', required=True)
    provider = fields.Selection([
        ('infobip', 'InfoBip'),
        ('twilio', 'Twilio'),
    ], 'Provider', required=True)
