# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreEmailConfig(models.Model):
    _name = 'contact.centre.email.config'
    _description = 'Contact Centre Email Configuration'

    name = fields.Char('Configuration Name', required=True)
    active = fields.Boolean('Active', default=True)
    # Link to Odoo outgoing mail server
    mail_server_id = fields.Many2one('ir.mail_server', 'Outgoing Mail Server',
                                     help='Mail server used to send emails from the contact centre')
    from_email = fields.Char('From Email Address')
    from_name = fields.Char('From Name')
