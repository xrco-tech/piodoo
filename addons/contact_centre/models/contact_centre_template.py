# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreTemplate(models.Model):
    _name = 'contact.centre.template'
    _description = 'Contact Centre Template'
    _inherit = ['mail.thread']

    name = fields.Char('Template Name', required=True, tracking=True)
    active = fields.Boolean('Active', default=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ], 'Channel', required=True, tracking=True)
    body_text = fields.Text('Template Body', required=True)
    notes = fields.Text('Notes')

    # WhatsApp-specific: link to native whatsapp template if applicable
    wa_template_id = fields.Many2one('whatsapp.template', 'WhatsApp Template',
                                     ondelete='set null',
                                     help='Link to the native WhatsApp template for sending')
