# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreEmailConfig(models.Model):
    """Email configuration for contact centre - TODO: Implement SMTP/sending"""
    _name = 'contact.centre.email.config'
    _description = 'Contact Centre Email Configuration'

    name = fields.Char('Configuration Name', required=True)
    active = fields.Boolean('Active', default=True)
