# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreScript(models.Model):
    _name = 'contact.centre.script'
    _description = 'Contact Centre Script'
    _inherit = ['mail.thread']

    name = fields.Char('Script Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('all', 'All Channels'),
    ], 'Channel', default='all')
    content_html = fields.Html('Script Content')
    notes = fields.Text('Internal Notes')
