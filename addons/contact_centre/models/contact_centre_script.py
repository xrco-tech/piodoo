# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreScript(models.Model):
    """Agent script model - TODO: Implement"""
    _name = 'contact.centre.script'
    _description = 'Contact Centre Script'

    name = fields.Char('Script Name', required=True)
    content_html = fields.Html('Script Content')
