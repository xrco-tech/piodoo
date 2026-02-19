# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreWhatsAppConfig(models.Model):
    """WhatsApp configuration - TODO: Implement"""
    _name = 'contact.centre.whatsapp.config'
    _description = 'WhatsApp Configuration'

    name = fields.Char('Configuration Name', required=True)
    account_id = fields.Char('Meta Business Account ID')
