# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreAutomation(models.Model):
    """Automation model - TODO: Implement"""
    _name = 'contact.centre.automation'
    _description = 'Contact Centre Automation'

    name = fields.Char('Automation Name', required=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('both', 'Both'),
    ], 'Channel', required=True)
