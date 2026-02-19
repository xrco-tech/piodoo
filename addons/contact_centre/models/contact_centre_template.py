# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreTemplate(models.Model):
    """Base template model - TODO: Implement"""
    _name = 'contact.centre.template'
    _description = 'Contact Centre Template'

    name = fields.Char('Template Name', required=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ], 'Channel', required=True)
    body_text = fields.Text('Template Body', required=True)
